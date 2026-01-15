"""
PBPK Workflow Steps - Concrete implementations for the PBPK pipeline.

Steps:
1. DownloadPapersStep - Download papers for drug PK parameters
2. CreateSnapshotStep - Create PK-Sim snapshot file
3. RunSimulationStep - Execute PK-Sim simulation
4. AnalyzeResultsStep - Analyze simulation outputs
5. GenerateReportStep - Generate report with plots
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .orchestrator import (
    WorkflowStep,
    WorkflowContext,
    StepResult,
    RetryConfig,
    RetryPolicy,
)
from .manifest import compute_file_checksum


@dataclass
class DownloadPapersStep(WorkflowStep):
    """Download papers for drug pharmacokinetic parameter research."""

    name: str = "download_papers"
    description: str = "Download papers containing PK parameters for the target drug"
    is_network_operation: bool = True

    def __init__(
        self,
        drug_name: str,
        max_papers: int = 5,
        output_subdir: str = "papers",
    ):
        super().__init__(
            name="download_papers",
            retry_config=RetryConfig(
                policy=RetryPolicy.EXPONENTIAL,
                max_retries=3,
                initial_delay_seconds=2.0,
            ),
            is_network_operation=True,
        )
        self.drug_name = drug_name
        self.max_papers = max_papers
        self.output_subdir = output_subdir

    def execute(self, context: WorkflowContext) -> StepResult:
        """Download papers and save to run directory."""
        output_dir = context.run_dir / "artifacts" / self.output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Import literature tools
            from biomni.tool.literature import (
                query_pubmed,
                download_pubmed_open_access_pdfs,
            )

            # Search for papers
            search_query = f"{self.drug_name} pharmacokinetics parameters"
            context.logger.info(f"Searching PubMed for: {search_query}")

            search_result = query_pubmed(search_query, retmax=self.max_papers * 2)

            if not search_result or "error" in str(search_result).lower():
                return StepResult(
                    success=False,
                    error=f"PubMed search failed: {search_result}",
                )

            # Extract PMIDs from search results
            pmids = []
            if isinstance(search_result, dict):
                pmids = search_result.get("pmids", [])[:self.max_papers]
            elif isinstance(search_result, list):
                pmids = search_result[:self.max_papers]

            if not pmids:
                context.logger.warning("No papers found, using placeholder")
                # Create placeholder file indicating no papers were found
                placeholder = output_dir / "no_papers_found.txt"
                placeholder.write_text(f"No open-access papers found for: {search_query}")
                return StepResult(
                    success=True,
                    outputs={"paper_count": 0, "papers_dir": str(output_dir)},
                    output_files=[placeholder],
                    validation_results={"papers_found": False},
                )

            # Download PDFs
            context.logger.info(f"Downloading {len(pmids)} papers...")
            download_result = download_pubmed_open_access_pdfs(
                pmids=pmids,
                output_dir=str(output_dir),
            )

            # Collect downloaded files
            pdf_files = list(output_dir.glob("*.pdf"))

            return StepResult(
                success=True,
                outputs={
                    "paper_count": len(pdf_files),
                    "papers_dir": str(output_dir),
                    "pmids": pmids,
                    "download_result": download_result,
                },
                output_files=pdf_files,
                validation_results={
                    "papers_found": len(pdf_files) > 0,
                    "all_requested_downloaded": len(pdf_files) >= len(pmids),
                },
            )

        except ImportError:
            context.logger.warning("Literature tools not available, skipping paper download")
            return StepResult(
                success=True,
                outputs={"paper_count": 0, "papers_dir": str(output_dir)},
                validation_results={"papers_found": False, "tools_available": False},
            )
        except Exception as e:
            return StepResult(
                success=False,
                error=str(e),
            )

    def is_idempotent_complete(self, context: WorkflowContext) -> bool:
        """Check if papers already exist."""
        output_dir = context.run_dir / "artifacts" / self.output_subdir
        if not output_dir.exists():
            return False
        pdf_files = list(output_dir.glob("*.pdf"))
        return len(pdf_files) >= self.max_papers

    def validate_postconditions(self, context: WorkflowContext, result: StepResult) -> tuple[bool, str]:
        """Validate paper download succeeded."""
        if not result.success:
            return False, result.error or "Download failed"
        # Allow zero papers if tools unavailable or no open-access papers found
        return True, ""


@dataclass
class CreateSnapshotStep(WorkflowStep):
    """Create PK-Sim snapshot file from drug parameters."""

    name: str = "create_snapshot"
    description: str = "Create PK-Sim snapshot JSON file with drug and simulation parameters"

    def __init__(
        self,
        drug_name: str,
        dose_mg: float = 100.0,
        molecular_weight: Optional[float] = None,
        log_p: Optional[float] = None,
        fraction_unbound: Optional[float] = None,
        solubility_mg_l: Optional[float] = None,
        simulation_duration_h: float = 24.0,
        allow_placeholders: bool = True,
    ):
        super().__init__(name="create_snapshot")
        self.drug_name = drug_name
        self.dose_mg = dose_mg
        self.molecular_weight = molecular_weight
        self.log_p = log_p
        self.fraction_unbound = fraction_unbound
        self.solubility_mg_l = solubility_mg_l
        self.simulation_duration_h = simulation_duration_h
        self.allow_placeholders = allow_placeholders

    def execute(self, context: WorkflowContext) -> StepResult:
        """Create the snapshot file."""
        from ..pbpk.pbpk_workflow import create_pbpk_snapshot

        output_dir = context.run_dir / "artifacts"
        snapshot_path = output_dir / f"{self.drug_name.lower()}_snapshot.json"

        result = create_pbpk_snapshot(
            drug_name=self.drug_name,
            dose_mg=self.dose_mg,
            molecular_weight=self.molecular_weight,
            log_p=self.log_p,
            fraction_unbound=self.fraction_unbound,
            solubility_mg_l=self.solubility_mg_l,
            simulation_duration_h=self.simulation_duration_h,
            out_path=str(snapshot_path),
            allow_placeholders=self.allow_placeholders,
        )

        if result.get("status") != "success":
            return StepResult(
                success=False,
                error=result.get("error", "Snapshot creation failed"),
                outputs=result,
            )

        return StepResult(
            success=True,
            outputs={
                "snapshot_path": str(snapshot_path),
                "drug_name": self.drug_name,
                "parameters": result.get("parameters", {}),
                "warnings": result.get("warnings", []),
            },
            output_files=[snapshot_path],
            validation_results={
                "file_exists": snapshot_path.exists(),
                "file_size": snapshot_path.stat().st_size if snapshot_path.exists() else 0,
            },
        )

    def is_idempotent_complete(self, context: WorkflowContext) -> bool:
        """Check if snapshot already exists and is valid."""
        output_dir = context.run_dir / "artifacts"
        snapshot_path = output_dir / f"{self.drug_name.lower()}_snapshot.json"

        if not snapshot_path.exists():
            return False

        # Validate it's a proper snapshot
        try:
            with open(snapshot_path, "r") as f:
                data = json.load(f)
            return "Version" in data and "Compounds" in data
        except Exception:
            return False

    def validate_preconditions(self, context: WorkflowContext) -> tuple[bool, str]:
        """Check that we have required parameters or allow placeholders."""
        if not self.allow_placeholders:
            missing = []
            if self.molecular_weight is None:
                missing.append("molecular_weight")
            if self.log_p is None:
                missing.append("log_p")
            if self.fraction_unbound is None:
                missing.append("fraction_unbound")
            if self.solubility_mg_l is None:
                missing.append("solubility_mg_l")
            if missing:
                return False, f"Missing required parameters: {', '.join(missing)}"
        return True, ""

    def validate_postconditions(self, context: WorkflowContext, result: StepResult) -> tuple[bool, str]:
        """Validate snapshot was created correctly."""
        if not result.success:
            return False, result.error or "Snapshot creation failed"

        snapshot_path = Path(result.outputs.get("snapshot_path", ""))
        if not snapshot_path.exists():
            return False, f"Snapshot file not found: {snapshot_path}"

        # Validate JSON structure
        try:
            with open(snapshot_path, "r") as f:
                data = json.load(f)

            required_keys = ["Version", "Compounds", "Individuals", "Simulations"]
            missing_keys = [k for k in required_keys if k not in data]
            if missing_keys:
                return False, f"Snapshot missing required keys: {missing_keys}"

            return True, ""
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON in snapshot: {e}"


@dataclass
class RunSimulationStep(WorkflowStep):
    """Run PK-Sim simulation from snapshot."""

    name: str = "run_simulation"
    description: str = "Execute PK-Sim simulation and export results"

    def __init__(
        self,
        timeout_seconds: int = 600,
        export_pkml: bool = True,
    ):
        super().__init__(
            name="run_simulation",
            timeout_seconds=timeout_seconds,
            retry_config=RetryConfig(
                policy=RetryPolicy.FIXED,
                max_retries=2,
                initial_delay_seconds=5.0,
            ),
        )
        self.timeout_seconds = timeout_seconds
        self.export_pkml = export_pkml

    def execute(self, context: WorkflowContext) -> StepResult:
        """Run the simulation."""
        from ..pbpk.pbpk_workflow import run_pbpk_simulation

        # Get snapshot path from previous step
        snapshot_path = context.get_step_output("create_snapshot", "snapshot_path")
        if not snapshot_path:
            # Try to find it in artifacts
            artifact_dir = context.run_dir / "artifacts"
            snapshots = list(artifact_dir.glob("*_snapshot.json"))
            if snapshots:
                snapshot_path = str(snapshots[0])
            else:
                return StepResult(
                    success=False,
                    error="No snapshot file found from previous step",
                )

        output_dir = context.run_dir / "artifacts" / "simulation_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Set environment for simulation
        os.environ["BIOMNI_CHAT_DIR"] = str(context.run_dir / "artifacts")

        result = run_pbpk_simulation(
            snapshot_path=snapshot_path,
            output_dir=str(output_dir),
            export_pkml=self.export_pkml,
            timeout_seconds=self.timeout_seconds,
            force_rerun=True,
        )

        if result.get("status") != "success":
            return StepResult(
                success=False,
                error=result.get("error", "Simulation failed"),
                outputs=result,
            )

        outputs = result.get("outputs", {})
        output_files = []

        # Collect output files
        results_csv = outputs.get("results_csv")
        if results_csv and Path(results_csv).exists():
            output_files.append(Path(results_csv))

        pkml_file = outputs.get("pkml_file")
        if pkml_file and Path(pkml_file).exists():
            output_files.append(Path(pkml_file))

        return StepResult(
            success=True,
            outputs={
                "output_dir": str(output_dir),
                "results_csv": results_csv,
                "pkml_file": pkml_file,
                "engine": result.get("engine", "unknown"),
            },
            output_files=output_files,
            validation_results={
                "has_results_csv": results_csv is not None and Path(results_csv).exists(),
                "has_pkml": pkml_file is not None and Path(pkml_file).exists(),
            },
        )

    def is_idempotent_complete(self, context: WorkflowContext) -> bool:
        """Check if simulation outputs already exist."""
        output_dir = context.run_dir / "artifacts" / "simulation_outputs"
        if not output_dir.exists():
            return False

        # Check for results CSV
        csv_files = list(output_dir.glob("*Results.csv")) + list(output_dir.glob("*-Results.csv"))
        return len(csv_files) > 0

    def validate_preconditions(self, context: WorkflowContext) -> tuple[bool, str]:
        """Check that snapshot exists."""
        snapshot_path = context.get_step_output("create_snapshot", "snapshot_path")
        if not snapshot_path:
            artifact_dir = context.run_dir / "artifacts"
            snapshots = list(artifact_dir.glob("*_snapshot.json"))
            if not snapshots:
                return False, "No snapshot file available for simulation"
        return True, ""

    def validate_postconditions(self, context: WorkflowContext, result: StepResult) -> tuple[bool, str]:
        """Validate simulation produced expected outputs."""
        if not result.success:
            return False, result.error or "Simulation failed"

        validation = result.validation_results
        if not validation.get("has_results_csv"):
            return False, "Simulation did not produce results CSV"

        return True, ""


@dataclass
class AnalyzeResultsStep(WorkflowStep):
    """Analyze simulation results and compute PK metrics."""

    name: str = "analyze_results"
    description: str = "Analyze simulation outputs and compute pharmacokinetic parameters"

    def __init__(self, timeout_seconds: int = 300):
        super().__init__(name="analyze_results", timeout_seconds=timeout_seconds)
        self.timeout_seconds = timeout_seconds

    def execute(self, context: WorkflowContext) -> StepResult:
        """Analyze the simulation results."""
        from ..pbpk.pbpk_workflow import analyze_pbpk_simulation_results

        # Get paths from previous step
        results_csv = context.get_step_output("run_simulation", "results_csv")
        pkml_file = context.get_step_output("run_simulation", "pkml_file")
        output_dir = context.get_step_output("run_simulation", "output_dir")

        if not output_dir:
            output_dir = str(context.run_dir / "artifacts" / "simulation_outputs")

        result = analyze_pbpk_simulation_results(
            output_dir=output_dir,
            results_csv_path=results_csv,
            pkml_path=pkml_file,
            timeout_seconds=self.timeout_seconds,
        )

        if result.get("status") != "success":
            return StepResult(
                success=False,
                error=result.get("error", "Analysis failed"),
                outputs=result,
            )

        # Save analysis summary
        analysis_path = context.run_dir / "artifacts" / "analysis_summary.json"
        with open(analysis_path, "w") as f:
            json.dump(result, f, indent=2, default=str)

        return StepResult(
            success=True,
            outputs={
                "analysis_path": str(analysis_path),
                "metrics": result.get("metrics", {}),
                "pk": result.get("pk", []),
                "engine": result.get("engine", "unknown"),
            },
            output_files=[analysis_path],
            validation_results={
                "has_metrics": len(result.get("metrics", {})) > 0 or len(result.get("pk", [])) > 0,
            },
        )

    def validate_preconditions(self, context: WorkflowContext) -> tuple[bool, str]:
        """Check that simulation outputs exist."""
        if not context.manifest.is_step_completed("run_simulation"):
            return False, "Simulation step not completed"
        return True, ""


@dataclass
class GenerateReportStep(WorkflowStep):
    """Generate report with plots from simulation results."""

    name: str = "generate_report"
    description: str = "Generate plots and summary report from simulation results"

    def __init__(
        self,
        plot_name: str = "pbpk_time_profile",
        dpi: int = 200,
        timeout_seconds: int = 600,
    ):
        super().__init__(name="generate_report", timeout_seconds=timeout_seconds)
        self.plot_name = plot_name
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds

    def execute(self, context: WorkflowContext) -> StepResult:
        """Generate plots and report."""
        from ..pbpk.pbpk_workflow import plot_pbpk_simulation_results

        # Get paths from previous steps
        pkml_file = context.get_step_output("run_simulation", "pkml_file")
        results_csv = context.get_step_output("run_simulation", "results_csv")
        output_dir = context.get_step_output("run_simulation", "output_dir")

        if not output_dir:
            output_dir = str(context.run_dir / "artifacts" / "simulation_outputs")

        # Generate plots
        plot_result = plot_pbpk_simulation_results(
            output_dir=output_dir,
            pkml_path=pkml_file,
            results_csv_path=results_csv,
            plot_name=self.plot_name,
            dpi=self.dpi,
            timeout_seconds=self.timeout_seconds,
        )

        output_files = []
        plot_file = None

        if plot_result.get("status") == "success":
            plot_file = plot_result.get("plot_file")
            if plot_file and Path(plot_file).exists():
                output_files.append(Path(plot_file))
        else:
            context.logger.warning(f"Plot generation failed: {plot_result.get('error')}")

        # Generate summary report
        report_path = context.run_dir / "artifacts" / "report.md"
        self._generate_markdown_report(context, report_path)
        output_files.append(report_path)

        return StepResult(
            success=True,
            outputs={
                "report_path": str(report_path),
                "plot_file": plot_file,
                "plots_dir": plot_result.get("plots_dir"),
            },
            output_files=output_files,
            validation_results={
                "has_report": report_path.exists(),
                "has_plot": plot_file is not None and Path(plot_file).exists(),
            },
        )

    def _generate_markdown_report(self, context: WorkflowContext, report_path: Path) -> None:
        """Generate a markdown summary report."""
        manifest = context.manifest

        # Gather info from steps
        drug_name = context.get_step_output("create_snapshot", "drug_name") or "Unknown"
        parameters = context.get_step_output("create_snapshot", "parameters") or {}
        metrics = context.get_step_output("analyze_results", "metrics") or {}
        pk = context.get_step_output("analyze_results", "pk") or []

        lines = [
            f"# PBPK Simulation Report: {drug_name}",
            "",
            f"**Run ID:** {manifest.run_id}",
            f"**Generated:** {manifest.completed_at or 'In Progress'}",
            "",
            "## Drug Parameters",
            "",
        ]

        for key, value in parameters.items():
            lines.append(f"- **{key}:** {value}")

        lines.extend([
            "",
            "## Simulation Results",
            "",
        ])

        if metrics:
            lines.append("### PK Metrics")
            lines.append("")
            for quantity, values in metrics.items():
                lines.append(f"**{quantity}:**")
                for k, v in values.items():
                    if isinstance(v, float):
                        lines.append(f"  - {k}: {v:.4g}")
                    else:
                        lines.append(f"  - {k}: {v}")
                lines.append("")

        if pk:
            lines.append("### PK Analysis (OSPSuite)")
            lines.append("")
            lines.append("| Parameter | Value | Unit |")
            lines.append("|-----------|-------|------|")
            for entry in pk[:20]:  # Limit to 20 rows
                param = entry.get("Parameter", "")
                value = entry.get("Value", "")
                unit = entry.get("Unit", "")
                if isinstance(value, float):
                    value = f"{value:.4g}"
                lines.append(f"| {param} | {value} | {unit} |")

        lines.extend([
            "",
            "## Workflow Summary",
            "",
            f"- **Total Duration:** {manifest.total_duration_seconds:.1f}s" if manifest.total_duration_seconds else "",
            f"- **Steps Completed:** {manifest.succeeded_count}/{manifest.step_count}",
            "",
        ])

        report_path.write_text("\n".join(lines), encoding="utf-8")

    def validate_preconditions(self, context: WorkflowContext) -> tuple[bool, str]:
        """Check that simulation completed."""
        if not context.manifest.is_step_completed("run_simulation"):
            return False, "Simulation step not completed"
        return True, ""


def create_pbpk_workflow_steps(
    drug_name: str,
    dose_mg: float = 100.0,
    molecular_weight: Optional[float] = None,
    log_p: Optional[float] = None,
    fraction_unbound: Optional[float] = None,
    solubility_mg_l: Optional[float] = None,
    simulation_duration_h: float = 24.0,
    download_papers: bool = False,
    allow_placeholders: bool = True,
) -> List[WorkflowStep]:
    """
    Create the standard PBPK workflow steps.

    Args:
        drug_name: Name of the drug
        dose_mg: Dose in milligrams
        molecular_weight: MW in g/mol
        log_p: Lipophilicity
        fraction_unbound: Plasma protein binding (fraction unbound)
        solubility_mg_l: Aqueous solubility at pH 7.4
        simulation_duration_h: Simulation duration in hours
        download_papers: Whether to include paper download step
        allow_placeholders: Allow placeholder values for missing parameters

    Returns:
        List of workflow steps
    """
    steps = []

    if download_papers:
        steps.append(DownloadPapersStep(drug_name=drug_name))

    steps.extend([
        CreateSnapshotStep(
            drug_name=drug_name,
            dose_mg=dose_mg,
            molecular_weight=molecular_weight,
            log_p=log_p,
            fraction_unbound=fraction_unbound,
            solubility_mg_l=solubility_mg_l,
            simulation_duration_h=simulation_duration_h,
            allow_placeholders=allow_placeholders,
        ),
        RunSimulationStep(),
        AnalyzeResultsStep(),
        GenerateReportStep(),
    ])

    return steps
