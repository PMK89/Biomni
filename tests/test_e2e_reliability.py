"""
End-to-end reliability tests for the PBPK workflow.

These tests verify that the full pipeline completes reliably:
1. Create snapshot
2. Run simulation (mocked)
3. Analyze results
4. Generate report

Target: >= 95% success rate over N runs.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import pytest

from biomni_esqlabs_tools.workflow.orchestrator import (
    WorkflowOrchestrator,
    WorkflowStep,
    WorkflowContext,
    StepResult,
    RetryConfig,
    RetryPolicy,
)
from biomni_esqlabs_tools.workflow.pbpk_steps import (
    CreateSnapshotStep,
    RunSimulationStep,
    AnalyzeResultsStep,
    GenerateReportStep,
    create_pbpk_workflow_steps,
)


# Test fixtures
BUPROPION_PARAMS = {
    "drug_name": "Bupropion",
    "dose_mg": 150.0,
    "molecular_weight": 239.74,
    "log_p": 3.6,
    "fraction_unbound": 0.16,
    "solubility_mg_l": 312.0,
    "simulation_duration_h": 24.0,
}


class MockSimulationStep(WorkflowStep):
    """Mock simulation step that creates fake outputs."""

    name: str = "run_simulation"

    def execute(self, context: WorkflowContext) -> StepResult:
        """Create mock simulation outputs."""
        output_dir = context.run_dir / "artifacts" / "simulation_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create mock results CSV
        results_csv = output_dir / "Bupropion_Simulation-Results.csv"
        csv_content = """IndividualId,Time [h],Bupropion|PeripheralVenousBlood|Plasma|Concentration [µmol/l]
0,0.0,0.0
0,0.5,2.1
0,1.0,4.5
0,2.0,6.2
0,4.0,5.8
0,8.0,3.2
0,12.0,1.8
0,24.0,0.5
"""
        results_csv.write_text(csv_content)

        # Create mock PKML file
        pkml_file = output_dir / "Bupropion_Simulation.pkml"
        pkml_file.write_text("<Simulation>Mock PKML</Simulation>")

        return StepResult(
            success=True,
            outputs={
                "output_dir": str(output_dir),
                "results_csv": str(results_csv),
                "pkml_file": str(pkml_file),
                "engine": "mock",
            },
            output_files=[results_csv, pkml_file],
            validation_results={
                "has_results_csv": True,
                "has_pkml": True,
            },
        )


class MockAnalysisStep(WorkflowStep):
    """Mock analysis step."""

    name: str = "analyze_results"

    def execute(self, context: WorkflowContext) -> StepResult:
        """Create mock analysis output."""
        analysis_path = context.run_dir / "artifacts" / "analysis_summary.json"
        analysis = {
            "status": "success",
            "metrics": {
                "Bupropion|Plasma|Concentration": {
                    "Cmax": 6.2,
                    "Tmax": 2.0,
                    "AUC_0_tEnd": 45.5,
                }
            },
        }
        analysis_path.write_text(json.dumps(analysis, indent=2))

        return StepResult(
            success=True,
            outputs={
                "analysis_path": str(analysis_path),
                "metrics": analysis["metrics"],
            },
            output_files=[analysis_path],
        )


class MockReportStep(WorkflowStep):
    """Mock report generation step."""

    name: str = "generate_report"

    def execute(self, context: WorkflowContext) -> StepResult:
        """Create mock report."""
        report_path = context.run_dir / "artifacts" / "report.md"
        report_content = """# PBPK Simulation Report

## Drug: Bupropion
## Dose: 150 mg

### Results
- Cmax: 6.2 µmol/L
- Tmax: 2.0 h
- AUC: 45.5 µmol·h/L
"""
        report_path.write_text(report_content)

        return StepResult(
            success=True,
            outputs={"report_path": str(report_path)},
            output_files=[report_path],
        )


def create_mock_workflow_steps(params: Dict[str, Any]) -> list:
    """Create workflow steps with mocked simulation."""
    return [
        CreateSnapshotStep(
            drug_name=params["drug_name"],
            dose_mg=params["dose_mg"],
            molecular_weight=params.get("molecular_weight"),
            log_p=params.get("log_p"),
            fraction_unbound=params.get("fraction_unbound"),
            solubility_mg_l=params.get("solubility_mg_l"),
            simulation_duration_h=params.get("simulation_duration_h", 24.0),
            allow_placeholders=True,
        ),
        MockSimulationStep(name="run_simulation"),
        MockAnalysisStep(name="analyze_results"),
        MockReportStep(name="generate_report"),
    ]


class TestE2EReliability:
    """End-to-end reliability tests."""

    def test_single_run_succeeds(self):
        """Test that a single workflow run completes successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = create_mock_workflow_steps(BUPROPION_PARAMS)
            orchestrator = WorkflowOrchestrator(
                workflow_name="pbpk_test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run(inputs=BUPROPION_PARAMS)

            assert success, f"Workflow failed: {[s.error for s in manifest.steps.values() if s.error]}"
            assert manifest.succeeded_count == 4
            assert manifest.failed_count == 0

            # Verify artifacts exist
            assert (manifest.run_dir / "artifacts" / "simulation_outputs" / "Bupropion_Simulation-Results.csv").exists()
            assert (manifest.run_dir / "artifacts" / "analysis_summary.json").exists()
            assert (manifest.run_dir / "artifacts" / "report.md").exists()

    def test_repeated_runs_reliability(self):
        """Test that repeated runs achieve >= 95% success rate."""
        n_runs = 20
        min_success_rate = 0.95

        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = WorkflowOrchestrator.run_repeated(
                workflow_name="pbpk_reliability_test",
                steps=create_mock_workflow_steps(BUPROPION_PARAMS),
                n_runs=n_runs,
                run_dir_base=Path(tmpdir),
                inputs=BUPROPION_PARAMS,
            )

            assert metrics["success_rate"] >= min_success_rate, (
                f"Success rate {metrics['success_rate']:.2%} < {min_success_rate:.2%}\n"
                f"Failures: {metrics['failure_reasons']}"
            )

    def test_manifest_contains_all_steps(self):
        """Test that manifest tracks all steps correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = create_mock_workflow_steps(BUPROPION_PARAMS)
            orchestrator = WorkflowOrchestrator(
                workflow_name="pbpk_test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            # All steps should be in manifest
            expected_steps = ["create_snapshot", "run_simulation", "analyze_results", "generate_report"]
            for step_name in expected_steps:
                assert step_name in manifest.steps, f"Missing step: {step_name}"
                assert manifest.steps[step_name].status.value == "SUCCEEDED"

    def test_manifest_persisted_and_loadable(self):
        """Test that manifest is properly persisted and can be loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = create_mock_workflow_steps(BUPROPION_PARAMS)
            orchestrator = WorkflowOrchestrator(
                workflow_name="pbpk_test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest1, _ = orchestrator.run()
            run_dir = manifest1.run_dir

            # Load the manifest from disk
            from biomni_esqlabs_tools.workflow.manifest import RunManifest
            manifest2 = RunManifest.load(run_dir)

            assert manifest2 is not None
            assert manifest2.run_id == manifest1.run_id
            assert manifest2.succeeded_count == manifest1.succeeded_count
            assert len(manifest2.steps) == len(manifest1.steps)

    def test_summary_json_generated(self):
        """Test that summary.json is generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = create_mock_workflow_steps(BUPROPION_PARAMS)
            orchestrator = WorkflowOrchestrator(
                workflow_name="pbpk_test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, _ = orchestrator.run()

            summary_path = manifest.run_dir / "summary.json"
            assert summary_path.exists()

            with open(summary_path) as f:
                summary = json.load(f)

            assert summary["status"] == "SUCCEEDED"
            assert summary["step_count"] == 4
            assert summary["succeeded_count"] == 4


class TestStepValidation:
    """Tests for step validation logic."""

    def test_snapshot_validation(self):
        """Test that snapshot step validates output correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            run_dir.mkdir()

            from biomni_esqlabs_tools.workflow.logging_config import setup_workflow_logging
            from biomni_esqlabs_tools.workflow.manifest import RunManifest

            manifest = RunManifest(run_id="test", run_dir=run_dir)
            logger = setup_workflow_logging("test", run_dir)
            context = WorkflowContext(
                run_id="test",
                run_dir=run_dir,
                manifest=manifest,
                logger=logger,
                inputs=BUPROPION_PARAMS,
            )

            step = CreateSnapshotStep(**BUPROPION_PARAMS)
            result = step.execute(context)

            assert result.success
            assert "snapshot_path" in result.outputs
            assert Path(result.outputs["snapshot_path"]).exists()

            # Validate postconditions
            valid, error = step.validate_postconditions(context, result)
            assert valid, f"Postcondition failed: {error}"

    def test_idempotency_check(self):
        """Test that steps correctly detect existing outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            run_dir.mkdir()
            (run_dir / "artifacts").mkdir()

            from biomni_esqlabs_tools.workflow.logging_config import setup_workflow_logging
            from biomni_esqlabs_tools.workflow.manifest import RunManifest

            manifest = RunManifest(run_id="test", run_dir=run_dir)
            logger = setup_workflow_logging("test", run_dir)
            context = WorkflowContext(
                run_id="test",
                run_dir=run_dir,
                manifest=manifest,
                logger=logger,
            )

            # Create a snapshot file
            snapshot_path = run_dir / "artifacts" / "bupropion_snapshot.json"
            snapshot_data = {
                "Version": 80,
                "Compounds": [{"Name": "Bupropion"}],
                "Individuals": [],
                "Simulations": [],
            }
            snapshot_path.write_text(json.dumps(snapshot_data))

            # Check idempotency
            step = CreateSnapshotStep(drug_name="Bupropion", allow_placeholders=True)
            assert step.is_idempotent_complete(context)


class TestErrorHandling:
    """Tests for error handling in the workflow."""

    def test_precondition_failure_stops_workflow(self):
        """Test that precondition failure prevents step execution."""

        class FailingPreconditionStep(WorkflowStep):
            def __init__(self):
                super().__init__(name="failing_step")

            def execute(self, context):
                return StepResult(success=True)

            def validate_preconditions(self, context):
                return False, "Required file not found"

        with tempfile.TemporaryDirectory() as tmpdir:
            steps = [FailingPreconditionStep()]
            orchestrator = WorkflowOrchestrator(
                workflow_name="test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            assert not success
            assert manifest.steps["failing_step"].status.value == "FAILED"
            assert "Precondition failed" in manifest.steps["failing_step"].error

    def test_step_exception_is_caught(self):
        """Test that exceptions in steps are properly caught and logged."""

        class ExceptionStep(WorkflowStep):
            def __init__(self):
                super().__init__(
                    name="exception_step",
                    retry_config=RetryConfig(policy=RetryPolicy.NONE),  # No retries for faster test
                )

            def execute(self, context):
                raise RuntimeError("Simulated crash")

        with tempfile.TemporaryDirectory() as tmpdir:
            steps = [ExceptionStep()]
            orchestrator = WorkflowOrchestrator(
                workflow_name="test",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            assert not success
            assert manifest.steps["exception_step"].status.value == "FAILED"
            assert "Simulated crash" in manifest.steps["exception_step"].error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
