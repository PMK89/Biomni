"""
Unit tests for the workflow orchestrator and manifest system.

These tests verify:
- Step execution and validation
- Retry logic with backoff
- Manifest persistence and resume
- Idempotency checks
"""

import json
import os
import tempfile
from pathlib import Path
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
from biomni_esqlabs_tools.workflow.manifest import (
    RunManifest,
    StepRecord,
    StepStatus,
    compute_file_checksum,
)


class SimpleStep(WorkflowStep):
    """A simple step for testing."""

    def __init__(self, name: str, should_succeed: bool = True, output_value: str = "test"):
        super().__init__(name=name)
        self.should_succeed = should_succeed
        self.output_value = output_value
        self.execute_count = 0

    def execute(self, context: WorkflowContext) -> StepResult:
        self.execute_count += 1
        if self.should_succeed:
            return StepResult(
                success=True,
                outputs={"value": self.output_value},
            )
        return StepResult(
            success=False,
            error="Simulated failure",
        )


class RetryableStep(WorkflowStep):
    """A step that fails a few times then succeeds."""

    def __init__(self, name: str, fail_count: int = 2):
        super().__init__(
            name=name,
            retry_config=RetryConfig(
                policy=RetryPolicy.FIXED,
                max_retries=3,
                initial_delay_seconds=0.01,
            ),
        )
        self.fail_count = fail_count
        self.attempt = 0

    def execute(self, context: WorkflowContext) -> StepResult:
        self.attempt += 1
        if self.attempt <= self.fail_count:
            return StepResult(
                success=False,
                error=f"Attempt {self.attempt} failed",
            )
        return StepResult(
            success=True,
            outputs={"attempts": self.attempt},
        )


class IdempotentStep(WorkflowStep):
    """A step that checks for existing outputs."""

    def __init__(self, name: str, output_file: str):
        super().__init__(name=name)
        self.output_file = output_file

    def execute(self, context: WorkflowContext) -> StepResult:
        output_path = context.run_dir / "artifacts" / self.output_file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("test output")
        return StepResult(
            success=True,
            outputs={"file": str(output_path)},
            output_files=[output_path],
        )

    def is_idempotent_complete(self, context: WorkflowContext) -> bool:
        output_path = context.run_dir / "artifacts" / self.output_file
        return output_path.exists()


class TestStepRecord:
    """Tests for StepRecord dataclass."""

    def test_to_dict(self):
        record = StepRecord(
            name="test_step",
            status=StepStatus.SUCCEEDED,
            started_at="2025-01-14T10:00:00Z",
            completed_at="2025-01-14T10:00:05Z",
            duration_seconds=5.0,
            outputs={"key": "value"},
        )
        d = record.to_dict()
        assert d["name"] == "test_step"
        assert d["status"] == "SUCCEEDED"
        assert d["duration_seconds"] == 5.0
        assert d["outputs"] == {"key": "value"}

    def test_from_dict(self):
        data = {
            "name": "test_step",
            "status": "FAILED",
            "error": "Something went wrong",
            "retry_count": 2,
        }
        record = StepRecord.from_dict(data)
        assert record.name == "test_step"
        assert record.status == StepStatus.FAILED
        assert record.error == "Something went wrong"
        assert record.retry_count == 2


class TestRunManifest:
    """Tests for RunManifest."""

    def test_create_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            manifest = RunManifest(
                run_id="test_123",
                run_dir=run_dir,
                workflow_name="test_workflow",
            )

            manifest.add_step("step1")
            manifest.add_step("step2")
            manifest.save()

            # Verify file exists
            assert (run_dir / "manifest.json").exists()

            # Verify content
            with open(run_dir / "manifest.json") as f:
                data = json.load(f)
            assert data["run_id"] == "test_123"
            assert "step1" in data["steps"]
            assert "step2" in data["steps"]

    def test_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            manifest = RunManifest(
                run_id="test_456",
                run_dir=run_dir,
            )
            manifest.add_step("step1")
            manifest.complete_step("step1", outputs={"result": 42})
            manifest.save()

            # Load the manifest
            loaded = RunManifest.load(run_dir)
            assert loaded is not None
            assert loaded.run_id == "test_456"
            assert loaded.steps["step1"].status == StepStatus.SUCCEEDED
            assert loaded.steps["step1"].outputs["result"] == 42

    def test_step_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            manifest = RunManifest(run_id="test_789", run_dir=run_dir)

            # Start a step
            step = manifest.start_step("my_step", inputs={"x": 1})
            assert step.status == StepStatus.RUNNING
            assert step.started_at is not None

            # Complete it
            manifest.complete_step("my_step", outputs={"y": 2})
            assert manifest.steps["my_step"].status == StepStatus.SUCCEEDED
            assert manifest.steps["my_step"].completed_at is not None
            assert manifest.steps["my_step"].duration_seconds is not None

    def test_fail_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            manifest = RunManifest(run_id="test_fail", run_dir=run_dir)

            manifest.start_step("failing_step")
            manifest.fail_step("failing_step", error="Test error", error_traceback="Traceback...")

            assert manifest.steps["failing_step"].status == StepStatus.FAILED
            assert manifest.steps["failing_step"].error == "Test error"
            assert manifest.failed_count == 1

    def test_is_resumable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            manifest = RunManifest(run_id="test_resume", run_dir=run_dir)

            manifest.add_step("step1")
            manifest.add_step("step2")
            manifest.complete_step("step1")

            assert manifest.is_resumable()
            assert "step2" in manifest.get_incomplete_steps()


class TestWorkflowOrchestrator:
    """Tests for WorkflowOrchestrator."""

    def test_simple_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = [
                SimpleStep("step1", output_value="first"),
                SimpleStep("step2", output_value="second"),
            ]

            orchestrator = WorkflowOrchestrator(
                workflow_name="test_workflow",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            assert success
            assert manifest.succeeded_count == 2
            assert manifest.failed_count == 0
            assert manifest.status == "SUCCEEDED"

    def test_workflow_with_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = [
                SimpleStep("step1"),
                SimpleStep("step2", should_succeed=False),
                SimpleStep("step3"),
            ]

            orchestrator = WorkflowOrchestrator(
                workflow_name="test_workflow",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            assert not success
            assert manifest.succeeded_count == 1
            assert manifest.failed_count == 1
            # Step 3 should not have run
            assert "step3" not in manifest.steps or manifest.steps["step3"].status == StepStatus.NOT_STARTED

    def test_retry_logic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            steps = [RetryableStep("retry_step", fail_count=2)]

            orchestrator = WorkflowOrchestrator(
                workflow_name="test_workflow",
                steps=steps,
                run_dir_base=Path(tmpdir),
            )

            manifest, success = orchestrator.run()

            assert success
            assert steps[0].attempt == 3  # Failed 2 times, succeeded on 3rd

    def test_idempotent_skip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # First run
            steps1 = [IdempotentStep("idem_step", "output.txt")]
            orchestrator1 = WorkflowOrchestrator(
                workflow_name="test_workflow",
                steps=steps1,
                run_dir_base=Path(tmpdir),
            )
            manifest1, success1 = orchestrator1.run()
            run_dir = manifest1.run_dir

            # Simulate second run in same directory
            steps2 = [IdempotentStep("idem_step", "output.txt")]
            orchestrator2 = WorkflowOrchestrator(
                workflow_name="test_workflow",
                steps=steps2,
                run_dir_base=Path(tmpdir),
            )

            # Create context to check idempotency
            from biomni_esqlabs_tools.workflow.logging_config import setup_workflow_logging

            logger = setup_workflow_logging("test", run_dir)
            context = WorkflowContext(
                run_id="test",
                run_dir=run_dir,
                manifest=manifest1,
                logger=logger,
            )

            # The step should recognize it's already complete
            assert steps2[0].is_idempotent_complete(context)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_exponential_backoff(self):
        config = RetryConfig(
            policy=RetryPolicy.EXPONENTIAL,
            initial_delay_seconds=1.0,
            multiplier=2.0,
            max_delay_seconds=10.0,
        )

        assert config.get_delay(0) == 0  # First attempt, no delay
        assert config.get_delay(1) == 1.0  # First retry
        assert config.get_delay(2) == 2.0  # Second retry
        assert config.get_delay(3) == 4.0  # Third retry
        assert config.get_delay(4) == 8.0  # Fourth retry
        assert config.get_delay(5) == 10.0  # Capped at max

    def test_fixed_delay(self):
        config = RetryConfig(
            policy=RetryPolicy.FIXED,
            initial_delay_seconds=5.0,
        )

        assert config.get_delay(0) == 0
        assert config.get_delay(1) == 5.0
        assert config.get_delay(2) == 5.0

    def test_no_retry(self):
        config = RetryConfig(policy=RetryPolicy.NONE)
        assert config.get_delay(0) == 0
        assert config.get_delay(1) == 0


class TestFileChecksum:
    """Tests for file checksum computation."""

    def test_compute_checksum(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test content")
            f.flush()
            path = Path(f.name)

        try:
            checksum = compute_file_checksum(path)
            assert len(checksum) == 16  # Truncated SHA256
            assert checksum.isalnum()
        finally:
            path.unlink()

    def test_checksum_nonexistent_file(self):
        checksum = compute_file_checksum(Path("/nonexistent/file.txt"))
        assert checksum == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
