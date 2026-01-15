"""
PBPK Workflow Tools - Reliable snapshot creation and simulation running.

These tools provide more deterministic snapshot creation and simulation
execution compared to the multi-step orchestration approach.
"""
from __future__ import annotations

import csv
import json
import os
import platform
import shutil
import subprocess
import textwrap
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_rscript_and_env() -> tuple[Optional[str], dict[str, str]]:
    conda_prefix = os.environ.get("CONDA_PREFIX") or sys.prefix

    rscript = shutil.which("Rscript")
    if conda_prefix:
        rscript_in_prefix = Path(conda_prefix) / "bin" / "Rscript"
        if rscript_in_prefix.exists():
            rscript = str(rscript_in_prefix)

    run_env = os.environ.copy()

    dotnet_exe = shutil.which("dotnet")
    dotnet_dir = None
    if not dotnet_exe and conda_prefix:
        cand1 = Path(conda_prefix) / "bin" / "dotnet"
        cand2 = Path(conda_prefix) / "lib" / "dotnet" / "dotnet"
        if cand1.exists():
            dotnet_dir = str(cand1.parent)
        elif cand2.exists():
            dotnet_dir = str(cand2.parent)

    if dotnet_dir:
        existing_path = run_env.get("PATH", "")
        run_env["PATH"] = f"{dotnet_dir}{os.pathsep}{existing_path}" if existing_path else dotnet_dir
        run_env.setdefault("DOTNET_ROOT", dotnet_dir)

    run_env.setdefault("LC_ALL", "en_US.UTF-8")
    return rscript, run_env


def _infer_results_csv_from_dir(output_dir: Path) -> Optional[Path]:
    candidates: list[Path] = []
    candidates.extend(sorted(output_dir.glob("*-Results.csv")))
    candidates.extend(sorted(output_dir.glob("*Results.csv")))
    candidates.extend(sorted(output_dir.glob("*.csv")))
    for cand in candidates:
        if cand.name.lower() == "simulation_outputs.csv":
            continue
        if cand.is_file():
            return cand
    return None


def _infer_pkml_from_dir(output_dir: Path) -> Optional[Path]:
    candidates = sorted(output_dir.glob("*.pkml"))
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _split_header_unit(header: str) -> tuple[str, Optional[str]]:
    header = header.strip().strip("\ufeff")
    if header.endswith("]") and "[" in header:
        base, unit = header.rsplit("[", 1)
        return base.strip().rstrip(), unit[:-1].strip()
    return header, None


def _normalize_csv_header(header: str) -> str:
    header = header.strip().strip("\ufeff")
    if len(header) >= 2 and header[0] == '"' and header[-1] == '"':
        header = header[1:-1]
    return header.strip().strip("\ufeff")


def _read_csv_headers(csv_path: Path) -> list[str]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        raw_headers = next(reader, [])
    return [_normalize_csv_header(h) for h in raw_headers]


def _trapezoid_auc(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    auc = 0.0
    for i in range(1, len(x)):
        dx = x[i] - x[i - 1]
        auc += dx * (y[i] + y[i - 1]) / 2.0
    return auc


def create_pbpk_snapshot(
    drug_name: str,
    dose_mg: float = 100.0,
    molecular_weight: Optional[float] = None,
    log_p: Optional[float] = None,
    fraction_unbound: Optional[float] = None,
    solubility_mg_l: Optional[float] = None,
    reference_ph: float = 7.4,
    individual_name: str = "HealthyAdult",
    population: str = "European_ICRP_2002",
    age_years: float = 30.0,
    weight_kg: float = 70.0,
    height_cm: float = 175.0,
    formulation_type: str = "Formulation_Tablet_Weibull",
    simulation_duration_h: float = 24.0,
    out_path: Optional[str] = None,
    allow_placeholders: bool = False,
) -> Dict[str, Any]:
    """
    Create a complete PK-Sim snapshot file for a drug with the provided parameters.

    This tool creates a valid PK-Sim snapshot JSON file that can be loaded
    into PK-Sim or used with run_pksim_snapshot for simulation.

    Args:
        drug_name: Name of the drug/compound (e.g., "Bupropion", "Ibuprofen")
        dose_mg: Dose in milligrams (default: 100.0)
        molecular_weight: Molecular weight in g/mol (required for PBPK)
        log_p: Lipophilicity (LogP value, required for PBPK)
        fraction_unbound: Fraction unbound in plasma (0-1, required for PBPK)
        solubility_mg_l: Solubility at reference pH in mg/L (required for PBPK)
        reference_ph: Reference pH for solubility (default: 7.4)
        individual_name: Name for the virtual individual (default: "HealthyAdult")
        population: Population model (default: "European_ICRP_2002")
        age_years: Age in years (default: 30.0)
        weight_kg: Body weight in kg (default: 70.0)
        height_cm: Height in cm (default: 175.0)
        formulation_type: PK-Sim formulation type (default: "Formulation_Tablet_Weibull")
        simulation_duration_h: Simulation duration in hours (default: 24.0)
        out_path: Output path for the snapshot file (auto-generated if not provided)

    Returns:
        Dict with status, file path, and snapshot content

    Example:
        >>> result = create_pbpk_snapshot(
        ...     drug_name="Bupropion",
        ...     dose_mg=150.0,
        ...     molecular_weight=239.74,
        ...     log_p=3.6,
        ...     fraction_unbound=0.16,
        ...     solubility_mg_l=312.0
        ... )
        >>> print(result["status"])
        "success"
    """
    # Validate required parameters
    missing_params = []
    if molecular_weight is None:
        missing_params.append("molecular_weight")
    if log_p is None:
        missing_params.append("log_p")
    if fraction_unbound is None:
        missing_params.append("fraction_unbound")
    if solubility_mg_l is None:
        missing_params.append("solubility_mg_l")

    warnings: list[str] = []
    if missing_params:
        if not allow_placeholders:
            return {
                "status": "error",
                "error": f"Missing required PK parameters: {', '.join(missing_params)}",
                "hint": "Please provide values for all required pharmacokinetic parameters. "
                        "Search for these values in scientific literature or databases like DrugBank.",
                "missing_parameters": missing_params,
            }

        # Use conservative placeholders so the snapshot is runnable.
        # These are NOT scientifically validated for the specific compound.
        placeholder_values = {
            "molecular_weight": 300.0,
            "log_p": 1.5,
            "fraction_unbound": 0.1,
            "solubility_mg_l": 100.0,
        }

        if molecular_weight is None:
            molecular_weight = placeholder_values["molecular_weight"]
            warnings.append("Using placeholder molecular_weight=300 g/mol")
        if log_p is None:
            log_p = placeholder_values["log_p"]
            warnings.append("Using placeholder log_p=1.5")
        if fraction_unbound is None:
            fraction_unbound = placeholder_values["fraction_unbound"]
            warnings.append("Using placeholder fraction_unbound=0.1")
        if solubility_mg_l is None:
            solubility_mg_l = placeholder_values["solubility_mg_l"]
            warnings.append("Using placeholder solubility_mg_l=100 mg/L")

    # Validate parameter ranges
    if not (0 < fraction_unbound <= 1):
        return {
            "status": "error",
            "error": f"fraction_unbound must be between 0 and 1 (got {fraction_unbound})",
            "hint": "Fraction unbound represents the unbound fraction of drug in plasma. "
                    "A value of 0.01 means 1% unbound (99% bound to proteins).",
        }

    # Create the snapshot structure
    snapshot = {
        "Version": 80,
        "Compounds": [{
            "Name": drug_name,
            "IsSmallMolecule": True,
            "Parameters": [
                {"Name": "Molecular weight", "Value": float(molecular_weight), "Unit": "g/mol"}
            ],
            "Lipophilicity": [{
                "Name": "Measurement",
                "Parameters": [
                    {"Name": "Lipophilicity", "Value": float(log_p), "Unit": "Log Units"}
                ]
            }],
            "FractionUnbound": [{
                "Name": "Measurement",
                "Species": "Human",
                "Parameters": [
                    {"Name": "Fraction unbound (plasma, reference value)", "Value": float(fraction_unbound)}
                ]
            }],
            "Solubility": [{
                "Name": "Assumption",
                "Parameters": [
                    {"Name": "Solubility at reference pH", "Value": float(solubility_mg_l), "Unit": "mg/l"},
                    {"Name": "Reference pH", "Value": float(reference_ph)}
                ]
            }]
        }],
        "Individuals": [{
            "Name": individual_name,
            "Age": {"Value": float(age_years), "Unit": "year(s)"},
            "Weight": {"Value": float(weight_kg), "Unit": "kg"},
            "Height": {"Value": float(height_cm), "Unit": "cm"},
            "OriginData": {
                "Species": "Human",
                "Population": population
            }
        }],
        "Formulations": [{
            "Name": "Oral_Formulation",
            "FormulationType": formulation_type
        }],
        "Protocols": [{
            "Name": "Protocol_Main",
            "Applications": [{
                "Name": "Application_1",
                "ApplicationType": "Oral",
                "FormulationKey": "Formulation",
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"}
                ]
            }],
            "Schemas": [{
                "Name": "Schema 1",
                "SchemaItems": [{
                    "Name": "Schema Item 1",
                    "ApplicationType": "Oral",
                    "FormulationKey": "Formulation",
                    "Parameters": [
                        {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                        {"Name": "InputDose", "Value": float(dose_mg), "Unit": "mg"},
                        {"Name": "Volume of water/body weight", "Value": 3.5, "Unit": "ml/kg"}
                    ]
                }],
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                    {"Name": "NumberOfRepetitions", "Value": 1.0},
                    {"Name": "TimeBetweenRepetitions", "Value": 24.0, "Unit": "h"}
                ]
            }],
            "TimeUnit": "h"
        }],
        "Simulations": [{
            "Name": f"{drug_name}_Simulation",
            "Model": "4Comp",
            "Individual": individual_name,
            "Compounds": [{
                "Name": drug_name,
                "Protocol": {
                    "Name": "Protocol_Main",
                    "Formulations": [{"Name": "Oral_Formulation", "Key": "Formulation"}]
                }
            }],
            "OutputSchema": [{
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                    {"Name": "End time", "Value": float(simulation_duration_h), "Unit": "h"},
                    {"Name": "Resolution", "Value": 4.0, "Unit": "pts/h"}
                ]
            }]
        }],
        "Events": [],
        "ExpressionProfiles": [],
        "ObservedData": [],
        "ObservedDataClassifications": [],
        "SimulationClassifications": []
    }

    # Determine output path
    if out_path is None:
        safe_name = drug_name.lower().replace(" ", "_").replace("-", "_")
        chat_dir = os.environ.get("BIOMNI_CHAT_DIR")
        if chat_dir:
            base_path = Path(chat_dir)
            candidate = base_path / f"{safe_name}_snapshot.json"
            if candidate.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                candidate = base_path / f"{safe_name}_snapshot_{timestamp}.json"
            out_path = str(candidate)
        else:
            # Use current working directory with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = f"{safe_name}_{timestamp}.json"

    # Ensure parent directory exists
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Write the snapshot file
    try:
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return {
            "status": "success",
            "message": f"PK-Sim snapshot created successfully for {drug_name}",
            "file_path": str(out_file.resolve()),
            "file_exists": out_file.exists(),
            "drug_name": drug_name,
            "dose_mg": dose_mg,
            "warnings": warnings,
            "parameters": {
                "molecular_weight": molecular_weight,
                "log_p": log_p,
                "fraction_unbound": fraction_unbound,
                "solubility_mg_l": solubility_mg_l,
            },
            "next_step": f"To run the simulation, use: run_pbpk_simulation(snapshot_path='{out_file.resolve()}')"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to write snapshot file: {str(e)}",
            "attempted_path": str(out_file),
        }


def run_pbpk_simulation(
    snapshot_path: str,
    pksim_cli_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    export_pkml: bool = True,
    force_rerun: bool = False,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """
    Run a PBPK simulation using PK-Sim CLI from a snapshot file.

    This tool executes a PK-Sim simulation and optionally exports results.
    Note: Requires PK-Sim to be installed on the system.

    Args:
        snapshot_path: Path to the PK-Sim snapshot JSON file
        pksim_cli_path: Path to PKSim.CLI.exe (auto-detected if not provided)
        output_dir: Directory for output files (uses snapshot directory if not provided)
        export_pkml: Whether to export PKML format (default: True)
        timeout_seconds: Timeout for simulation in seconds (default: 300)

    Returns:
        Dict with status, output files, and any error messages

    Example:
        >>> result = run_pbpk_simulation(snapshot_path="bupropion_snapshot.json")
        >>> print(result["status"])
        "success"
    """
    # Validate snapshot file exists
    snapshot_file = Path(snapshot_path)
    if not snapshot_file.exists():
        return {
            "status": "error",
            "error": f"Snapshot file not found: {snapshot_path}",
            "hint": "Use create_pbpk_snapshot to create a valid snapshot file first.",
        }

    # Determine output directory early so we can reuse existing outputs if available
    if output_dir is None:
        chat_dir = os.environ.get("BIOMNI_CHAT_DIR")
        if chat_dir:
            output_dir = str(Path(chat_dir) / "simulation_outputs")
        else:
            output_dir = str(snapshot_file.parent / "simulation_outputs")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    inferred_csv = _infer_results_csv_from_dir(output_path) if output_path.exists() else None
    inferred_pkml = _infer_pkml_from_dir(output_path) if output_path.exists() else None
    if not force_rerun and (inferred_csv or inferred_pkml):
        outputs_existing: Dict[str, Any] = {
            "output_dir": str(output_path.resolve()),
            "results_csv": str(inferred_csv.resolve()) if inferred_csv else None,
            "pkml_file": str(inferred_pkml.resolve()) if inferred_pkml else None,
        }
        return {
            "status": "success",
            "message": "Using existing PBPK simulation outputs found on disk",
            "snapshot_path": str(snapshot_file),
            "outputs": outputs_existing,
            "engine": "existing",
        }

    # Try to find PK-Sim CLI
    if pksim_cli_path is None:
        pksim_cli_path = os.environ.get("PKSIM_CLI")

    if pksim_cli_path is None:
        # Check common installation paths
        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\PK-Sim 12\PKSim.CLI.exe",
                r"C:\Program Files\PK-Sim 11\PKSim.CLI.exe",
                r"C:\Program Files\Open Systems Pharmacology\PK-Sim\PKSim.CLI.exe",
            ]
        else:
            # On Linux/WSL, check if running under WSL
            common_paths = [
                "/mnt/c/Program Files/PK-Sim 12/PKSim.CLI.exe",
                "/mnt/c/Program Files/PK-Sim 11/PKSim.CLI.exe",
            ]

        for path in common_paths:
            if os.path.exists(path):
                pksim_cli_path = path
                break

    engine = (os.environ.get("BIOMNI_PBPK_ENGINE") or "auto").strip().lower()

    if pksim_cli_path is None or not os.path.exists(pksim_cli_path):
        if engine in {"auto", "ospsuite", "r", "ospsuite-r"}:
            return _run_pbpk_simulation_ospsuite_r(
                snapshot_path=str(snapshot_file),
                output_dir=output_dir,
                export_pkml=export_pkml,
                timeout_seconds=timeout_seconds,
                checked_paths=common_paths if 'common_paths' in dir() else [],
            )

        return {
            "status": "error",
            "error": "PK-Sim CLI not found",
            "hint": "Please install PK-Sim or set the PKSIM_CLI environment variable to the path of PKSim.CLI.exe. "
                    "Alternatively set BIOMNI_PBPK_ENGINE=ospsuite to run via OSPSuite-R on Linux.",
            "checked_paths": common_paths if 'common_paths' in dir() else [],
        }

    # output_dir/output_path already resolved above

    # Build project from snapshot
    project_name = snapshot_file.stem + ".pksim5"
    project_path = output_path / project_name

    try:
        # Run PK-Sim CLI to build project from snapshot
        build_cmd = [
            pksim_cli_path,
            "snap", "-p",
            "--input", str(snapshot_file),
            "--output", str(project_path),
        ]

        result = subprocess.run(
            build_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )

        if result.returncode != 0:
            return {
                "status": "error",
                "error": "PK-Sim CLI failed to build project",
                "stderr": result.stderr,
                "stdout": result.stdout,
                "command": " ".join(build_cmd),
            }

        outputs = {
            "project_file": str(project_path) if project_path.exists() else None,
        }

        # Export PKML if requested
        if export_pkml and project_path.exists():
            pkml_path = output_path / (snapshot_file.stem + ".pkml")

            # Read snapshot to get simulation name
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                snapshot_data = json.load(f)

            sim_name = None
            if snapshot_data.get("Simulations") and len(snapshot_data["Simulations"]) > 0:
                sim_name = snapshot_data["Simulations"][0].get("Name", "Simulation")

            if sim_name:
                export_cmd = [
                    pksim_cli_path,
                    "export", "-k",
                    "--project", str(project_path),
                    "--output", str(output_path),
                    "--simulations", sim_name,
                ]

                export_result = subprocess.run(
                    export_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    shell=False,
                )

                if export_result.returncode == 0:
                    # Find the exported PKML file
                    pkml_files = list(output_path.glob("*.pkml"))
                    if pkml_files:
                        outputs["pkml_file"] = str(pkml_files[0])

        inferred_csv = _infer_results_csv_from_dir(output_path) if output_path.exists() else None
        inferred_pkml = _infer_pkml_from_dir(output_path) if output_path.exists() else None
        if inferred_csv:
            outputs["results_csv"] = str(inferred_csv.resolve())
        if inferred_pkml and "pkml_file" not in outputs:
            outputs["pkml_file"] = str(inferred_pkml.resolve())

        produced_files = sorted(str(p.resolve()) for p in output_path.glob("**/*") if p.is_file())
        outputs["files"] = produced_files

        if not produced_files:
            return {
                "status": "error",
                "error": "PBPK simulation did not produce any output files",
                "snapshot_path": str(snapshot_file),
                "output_dir": str(output_path.resolve()),
                "pksim_cli": pksim_cli_path,
                "hint": "The simulation command returned success, but no artifacts were written. Check PK-Sim CLI installation and permissions.",
            }

        return {
            "status": "success",
            "message": "PBPK simulation completed successfully",
            "snapshot_path": str(snapshot_file),
            "outputs": outputs,
            "pksim_cli": pksim_cli_path,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"Simulation timed out after {timeout_seconds} seconds",
            "hint": "Try increasing the timeout_seconds parameter for complex simulations.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error running simulation: {str(e)}",
        }


def run_pbpk_workflow(
    *,
    snapshot_path: str,
    output_dir: Optional[str] = None,
    export_pkml: bool = True,
    timeout_seconds: int = 600,
    force_rerun: bool = False,
    run_analysis: bool = True,
    run_plot: bool = True,
    plot_name: str = "pbpk_time_profile",
    dpi: int = 200,
) -> Dict[str, Any]:
    resolved_output_dir: Optional[str] = output_dir
    if resolved_output_dir is None:
        chat_dir = os.environ.get("BIOMNI_CHAT_DIR")
        if chat_dir:
            resolved_output_dir = str(Path(chat_dir) / "simulation_outputs")

    sim = run_pbpk_simulation(
        snapshot_path=snapshot_path,
        output_dir=resolved_output_dir,
        export_pkml=export_pkml,
        force_rerun=force_rerun,
        timeout_seconds=timeout_seconds,
    )

    if sim.get("status") != "success":
        return {
            "status": "error",
            "error": "PBPK workflow failed during simulation",
            "simulation": sim,
        }

    outputs = (sim.get("outputs") or {}) if isinstance(sim, dict) else {}
    out_dir = Path(outputs.get("output_dir") or (resolved_output_dir or ""))

    results_csv = outputs.get("results_csv")
    pkml_file = outputs.get("pkml_file")

    produced_files = []
    try:
        if out_dir and out_dir.exists():
            produced_files = sorted(str(p.resolve()) for p in out_dir.glob("**/*") if p.is_file())
    except Exception:
        produced_files = []

    if not produced_files:
        return {
            "status": "error",
            "error": "PBPK workflow did not find any produced files after simulation",
            "simulation": sim,
        }

    analysis: Dict[str, Any] | None = None
    if run_analysis:
        analysis = analyze_pbpk_simulation_results(
            output_dir=str(out_dir) if str(out_dir) else None,
            results_csv_path=results_csv,
            pkml_path=pkml_file,
            timeout_seconds=timeout_seconds,
        )
        try:
            if out_dir and out_dir.exists():
                (out_dir / "pbpk_analysis_summary.json").write_text(
                    json.dumps(analysis, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception:
            pass

    plot: Dict[str, Any] | None = None
    if run_plot:
        plot = plot_pbpk_simulation_results(
            output_dir=str(out_dir) if str(out_dir) else None,
            pkml_path=pkml_file,
            results_csv_path=results_csv,
            plot_name=plot_name,
            dpi=dpi,
            timeout_seconds=timeout_seconds,
        )

    return {
        "status": "success",
        "simulation": sim,
        "outputs": {
            **outputs,
            "files": produced_files,
        },
        "analysis": analysis,
        "plot": plot,
    }


def _run_pbpk_simulation_ospsuite_r(
    *,
    snapshot_path: str,
    output_dir: str,
    export_pkml: bool,
    timeout_seconds: int,
    checked_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rscript, run_env = _get_rscript_and_env()
    if not rscript:
        return {
            "status": "error",
            "error": "PK-Sim CLI not found and Rscript is not available for OSPSuite-R fallback",
            "hint": "Install R + OSPSuite-R in the container or set BIOMNI_PBPK_ENGINE=auto to use PK-Sim CLI when available.",
            "checked_paths": checked_paths or [],
        }

    snapshot_file = Path(snapshot_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    r_code = textwrap.dedent(
        """
        args <- commandArgs(trailingOnly = TRUE)
        snapshot_path <- args[[1]]
        output_dir <- args[[2]]
        export_pkml <- as.logical(args[[3]])

        suppressPackageStartupMessages({
          library(ospsuite)
          library(jsonlite)
        })

        dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

        runSimulationsFromSnapshot(
          snapshot_path,
          output = output_dir,
          exportCSV = TRUE,
          exportPKML = export_pkml
        )

        files <- list.files(output_dir, recursive = TRUE, full.names = TRUE)
        cat(toJSON(list(
          ok = TRUE,
          snapshot_path = snapshot_path,
          output_dir = output_dir,
          files = files
        ), auto_unbox = TRUE))
        """
    ).strip()

    try:
        completed = subprocess.run(
            [rscript, "-e", r_code, str(snapshot_file), str(output_path), "TRUE" if export_pkml else "FALSE"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            env=run_env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"OSPSuite-R simulation timed out after {timeout_seconds} seconds",
            "hint": "Try increasing timeout_seconds.",
        }

    if completed.returncode != 0:
        inferred_csv = _infer_results_csv_from_dir(output_path) if output_path.exists() else None
        inferred_pkml = _infer_pkml_from_dir(output_path) if output_path.exists() else None
        if inferred_csv or inferred_pkml:
            outputs: Dict[str, Any] = {
                "output_dir": str(output_path.resolve()),
                "files": sorted(str(p) for p in output_path.glob("**/*") if p.is_file()),
                "results_csv": str(inferred_csv.resolve()) if inferred_csv else None,
                "pkml_file": str(inferred_pkml.resolve()) if inferred_pkml else None,
            }
            return {
                "status": "success",
                "message": "PBPK outputs were generated, but OSPSuite-R reported a non-zero exit code",
                "snapshot_path": str(snapshot_file),
                "outputs": outputs,
                "engine": "ospsuite-r",
                "warning": {
                    "stderr": completed.stderr,
                    "stdout": completed.stdout,
                },
            }
        return {
            "status": "error",
            "error": "OSPSuite-R simulation failed",
            "stderr": completed.stderr,
            "stdout": completed.stdout,
            "hint": "Ensure OSPSuite-R is installed in the runtime and that its prerequisites (rSharp + .NET 8) are available.",
        }

    stdout = (completed.stdout or "").strip()
    try:
        summary = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        summary = {"raw_stdout": stdout}

    inferred_csv = _infer_results_csv_from_dir(output_path) if output_path.exists() else None
    inferred_pkml = _infer_pkml_from_dir(output_path) if output_path.exists() else None
    produced_files = sorted(str(p.resolve()) for p in output_path.glob("**/*") if p.is_file())

    outputs: Dict[str, Any] = {
        "output_dir": str(output_path),
        "files": summary.get("files", []) or produced_files,
        "results_csv": str(inferred_csv.resolve()) if inferred_csv else None,
        "pkml_file": str(inferred_pkml.resolve()) if inferred_pkml else None,
    }

    if not outputs["files"]:
        return {
            "status": "error",
            "error": "OSPSuite-R simulation returned success but produced no output files",
            "snapshot_path": str(snapshot_file),
            "output_dir": str(output_path.resolve()),
            "hint": "Check that OSPSuite-R can write to the output directory and that the snapshot is valid.",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    return {
        "status": "success",
        "message": "PBPK simulation completed successfully (OSPSuite-R backend)",
        "snapshot_path": str(snapshot_file),
        "outputs": outputs,
        "engine": "ospsuite-r",
    }


def analyze_pbpk_simulation_results(
    *,
    output_dir: Optional[str] = None,
    results_csv_path: Optional[str] = None,
    pkml_path: Optional[str] = None,
    quantity_paths: Optional[List[str]] = None,
    individual_id: int = 0,
    use_ospsuite: bool = True,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Analyze PBPK simulation results and compute PK metrics."""

    resolved_output_dir: Optional[Path] = None
    if output_dir:
        resolved_output_dir = Path(output_dir)
    elif os.environ.get("BIOMNI_CHAT_DIR"):
        resolved_output_dir = Path(os.environ["BIOMNI_CHAT_DIR"]) / "simulation_outputs"

    csv_file: Optional[Path] = Path(results_csv_path) if results_csv_path else None
    if csv_file is None and resolved_output_dir and resolved_output_dir.exists():
        csv_file = _infer_results_csv_from_dir(resolved_output_dir)

    if csv_file is None or not csv_file.exists():
        return {
            "status": "error",
            "error": "Results CSV not found",
            "hint": "Provide results_csv_path or output_dir containing an exported '*-Results.csv' file.",
            "output_dir": str(resolved_output_dir) if resolved_output_dir else None,
        }

    if pkml_path is None and resolved_output_dir and resolved_output_dir.exists():
        inferred_pkml = _infer_pkml_from_dir(resolved_output_dir)
        if inferred_pkml:
            pkml_path = str(inferred_pkml)

    if use_ospsuite and pkml_path:
        rscript, run_env = _get_rscript_and_env()
        if rscript:
            qpaths = quantity_paths or []
            if not qpaths:
                headers = _read_csv_headers(csv_file)
                qpaths = [h for h in headers if h not in {"IndividualId", "Time [min]", "Time [h]", "Time"}]
                qpaths = qpaths[:5]
            qpaths = [_split_header_unit(q)[0] for q in qpaths]

            r_code = textwrap.dedent(
                """
                args <- commandArgs(trailingOnly = TRUE)
                pkml_path <- args[[1]]
                output_dir <- args[[2]]
                qpaths_json <- args[[3]]
                individual_id <- as.integer(args[[4]])
                results_csv <- args[[5]]

                suppressPackageStartupMessages({
                  library(ospsuite)
                  library(jsonlite)
                })

                qpaths <- fromJSON(qpaths_json)
                if (length(qpaths) == 0) {
                  qpaths <- NULL
                }

                sim <- loadSimulation(pkml_path)
                sim_res <- NULL
                if (!is.null(results_csv) && nzchar(results_csv) && file.exists(results_csv)) {
                  sim_res <- importResultsFromCSV(sim, results_csv)
                } else {
                  res_list <- runSimulations(simulations = sim)
                  sim_res <- res_list[[1]]
                }
                if (!is.null(qpaths)) {
                  qpaths <- intersect(qpaths, sim_res$allQuantityPaths)
                  if (length(qpaths) == 0) {
                    qpaths <- NULL
                  }
                }
                pk <- calculatePKAnalyses(simulationResults = sim_res, quantitiesOrPaths = qpaths)
                df <- pkAnalysesToDataFrame(pk)
                if (!is.null(individual_id)) {
                  df <- df[df$IndividualId == individual_id,]
                }
                cat(toJSON(list(ok = TRUE, pk = df), dataframe = "rows", auto_unbox = TRUE))
                """
            ).strip()

            out_dir_for_r = str((resolved_output_dir or csv_file.parent).resolve())
            completed = subprocess.run(
                [
                    rscript,
                    "-e",
                    r_code,
                    str(Path(pkml_path).resolve()),
                    out_dir_for_r,
                    json.dumps(qpaths),
                    str(individual_id),
                    str(csv_file.resolve()),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
                env=run_env,
            )
            if completed.returncode == 0:
                stdout = (completed.stdout or "").strip()
                try:
                    payload = json.loads(stdout) if stdout else {}
                    if payload.get("ok"):
                        return {
                            "status": "success",
                            "engine": "ospsuite-r",
                            "results_csv": str(csv_file.resolve()),
                            "pkml_path": str(Path(pkml_path).resolve()),
                            "pk": payload.get("pk", []),
                        }
                except json.JSONDecodeError:
                    pass

    headers = _read_csv_headers(csv_file)
    with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
        _ = next(f, None)
        reader = csv.DictReader(f, fieldnames=headers)
        if not headers:
            return {
                "status": "error",
                "error": "Results CSV appears to have no headers",
                "results_csv": str(csv_file.resolve()),
            }

        fieldnames = headers
        time_key = None
        for candidate in ("Time [min]", "Time [h]", "Time"):
            if candidate in fieldnames:
                time_key = candidate
                break

        if time_key is None:
            return {
                "status": "error",
                "error": "Could not find a Time column in results CSV",
                "results_csv": str(csv_file.resolve()),
                "available_columns": fieldnames,
            }

        if "IndividualId" not in fieldnames:
            return {
                "status": "error",
                "error": "Could not find IndividualId column in results CSV",
                "results_csv": str(csv_file.resolve()),
                "available_columns": fieldnames,
            }

        quantity_cols = [c for c in fieldnames if c not in {"IndividualId", time_key}]
        if quantity_paths:
            quantity_cols = [c for c in quantity_cols if c in set(quantity_paths)]

        rows: list[dict[str, str]] = []
        for row in reader:
            if str(row.get("IndividualId", "")).strip() != str(individual_id):
                continue
            rows.append(row)

    if not rows:
        return {
            "status": "error",
            "error": f"No rows found for IndividualId={individual_id}",
            "results_csv": str(csv_file.resolve()),
        }

    time_raw: list[float] = []
    for r in rows:
        try:
            time_raw.append(float(r[time_key]))
        except Exception:
            time_raw.append(float("nan"))

    if time_key == "Time [min]":
        time_h = [t / 60.0 for t in time_raw]
        time_unit = "h"
    elif time_key == "Time [h]":
        time_h = time_raw
        time_unit = "h"
    else:
        time_h = time_raw
        time_unit = "unknown"

    metrics: dict[str, Any] = {}
    for col in quantity_cols:
        y: list[float] = []
        for r in rows:
            val = r.get(col, "")
            try:
                y.append(float(val))
            except Exception:
                y.append(float("nan"))

        valid_pairs = [(t, v) for t, v in zip(time_h, y) if (t == t and v == v)]
        if len(valid_pairs) < 2:
            continue

        valid_pairs.sort(key=lambda tv: tv[0])
        t_sorted = [tv[0] for tv in valid_pairs]
        v_sorted = [tv[1] for tv in valid_pairs]

        cmax = max(v_sorted)
        imax = v_sorted.index(cmax)
        tmax = t_sorted[imax]
        auc = _trapezoid_auc(t_sorted, v_sorted)

        base_name, unit = _split_header_unit(col)
        metrics[col] = {
            "quantity": base_name,
            "unit": unit,
            "Cmax": cmax,
            "Tmax": tmax,
            "AUC_0_tEnd": auc,
            "time_unit": time_unit,
        }

    return {
        "status": "success",
        "engine": "csv",
        "results_csv": str(csv_file.resolve()),
        "pkml_path": str(Path(pkml_path).resolve()) if pkml_path else None,
        "individual_id": individual_id,
        "available_quantity_columns": quantity_cols,
        "metrics": metrics,
    }


def plot_pbpk_simulation_results(
    *,
    output_dir: Optional[str] = None,
    pkml_path: Optional[str] = None,
    results_csv_path: Optional[str] = None,
    quantity_paths: Optional[List[str]] = None,
    plot_name: str = "pbpk_time_profile",
    file_format: str = "png",
    dpi: int = 200,
    timeout_seconds: int = 600,
) -> Dict[str, Any]:
    """Plot PBPK simulation results using OSPSuite-R plotting utilities."""

    resolved_output_dir: Optional[Path] = None
    if output_dir:
        resolved_output_dir = Path(output_dir)
    elif os.environ.get("BIOMNI_CHAT_DIR"):
        resolved_output_dir = Path(os.environ["BIOMNI_CHAT_DIR"]) / "simulation_outputs"

    csv_file = Path(results_csv_path) if results_csv_path else None
    if csv_file is None and resolved_output_dir and resolved_output_dir.exists():
        csv_file = _infer_results_csv_from_dir(resolved_output_dir)

    if pkml_path is None and resolved_output_dir and resolved_output_dir.exists():
        inferred_pkml = _infer_pkml_from_dir(resolved_output_dir)
        if inferred_pkml:
            pkml_path = str(inferred_pkml)

    plots_dir = (resolved_output_dir or (csv_file.parent if csv_file else None) or (Path(pkml_path).parent if pkml_path else Path.cwd())) / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    rscript, run_env = _get_rscript_and_env()
    if not rscript:
        # Fallback: basic plotting from CSV using matplotlib, if available.
        if csv_file is None or not csv_file.exists():
            return {
                "status": "error",
                "error": "Rscript not available and Results CSV not found for fallback plotting",
                "hint": "Install R + OSPSuite-R for PKML plotting or provide results_csv_path/output_dir with results CSV.",
                "output_dir": str(resolved_output_dir) if resolved_output_dir else None,
            }
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception:
            return {
                "status": "error",
                "error": "Rscript not available and matplotlib is not installed for CSV fallback plotting",
                "hint": "Install R + OSPSuite-R, or add matplotlib to the Python environment.",
                "results_csv": str(csv_file.resolve()),
            }

        headers = _read_csv_headers(csv_file)
        time_key = None
        for candidate in ("Time [h]", "Time [min]", "Time"):
            if candidate in headers:
                time_key = candidate
                break
        if time_key is None:
            return {
                "status": "error",
                "error": "Could not find a Time column in results CSV for plotting",
                "results_csv": str(csv_file.resolve()),
                "available_columns": headers,
            }

        import csv as _csv

        quantity_cols = [h for h in headers if h not in {"IndividualId", time_key}]
        if quantity_paths:
            quantity_cols = [c for c in quantity_cols if c in set(quantity_paths)]
        quantity_cols = quantity_cols[:3]
        if not quantity_cols:
            return {
                "status": "error",
                "error": "No quantity columns found in results CSV for plotting",
                "results_csv": str(csv_file.resolve()),
            }

        time_vals: list[float] = []
        series: dict[str, list[float]] = {c: [] for c in quantity_cols}

        with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # Prefer IndividualId=0 when available.
                if "IndividualId" in row and str(row.get("IndividualId", "")).strip() not in ("", "0"):
                    continue
                try:
                    t = float(row.get(time_key, ""))
                except Exception:
                    continue
                if time_key == "Time [min]":
                    t = t / 60.0
                time_vals.append(t)
                for c in quantity_cols:
                    try:
                        series[c].append(float(row.get(c, "")))
                    except Exception:
                        series[c].append(float("nan"))

        if not time_vals:
            return {
                "status": "error",
                "error": "No data rows found for plotting",
                "results_csv": str(csv_file.resolve()),
            }

        plot_path = (plots_dir / f"{plot_name}.{file_format}").resolve()
        plt.figure(figsize=(12, 7))
        for c in quantity_cols:
            plt.plot(time_vals, series[c], label=c)
        plt.xlabel("Time [h]")
        plt.ylabel("Value")
        plt.legend(loc="best", fontsize=7)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=dpi)
        plt.close()

        if not plot_path.exists():
            return {
                "status": "error",
                "error": "CSV fallback plot was not created on disk",
                "expected_plot": str(plot_path),
            }

        return {
            "status": "success",
            "engine": "matplotlib",
            "results_csv": str(csv_file.resolve()),
            "plots_dir": str(plots_dir.resolve()),
            "plot_file": str(plot_path),
            "quantity_paths": quantity_cols,
        }

    if not pkml_path or not Path(pkml_path).exists():
        return {
            "status": "error",
            "error": "PKML file not found for plotting",
            "hint": "Provide pkml_path or output_dir containing an exported .pkml file.",
            "output_dir": str(resolved_output_dir) if resolved_output_dir else None,
        }

    if not quantity_paths and csv_file and csv_file.exists():
        headers = _read_csv_headers(csv_file)
        quantity_paths = [h for h in headers if h not in {"IndividualId", "Time [min]", "Time [h]", "Time"}]
        quantity_paths = quantity_paths[:3]
    if quantity_paths:
        quantity_paths = [_split_header_unit(q)[0] for q in quantity_paths]

    # (Rscript is available here; plotting continues via OSPSuite-R)

    r_code = textwrap.dedent(
        """
        args <- commandArgs(trailingOnly = TRUE)
        pkml_path <- args[[1]]
        output_dir <- args[[2]]
        qpaths_json <- args[[3]]
        plot_name <- args[[4]]
        file_format <- args[[5]]
        dpi <- as.numeric(args[[6]])
        results_csv <- args[[7]]

        suppressPackageStartupMessages({
          library(ospsuite)
          library(jsonlite)
          library(tlf)
        })

        has_ggplot <- requireNamespace("ggplot2", quietly = TRUE)

        qpaths <- fromJSON(qpaths_json)
        if (length(qpaths) == 0) {
          qpaths <- NULL
        }

        dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

        sim <- loadSimulation(pkml_path)
        sim_res <- NULL
        if (!is.null(results_csv) && nzchar(results_csv) && file.exists(results_csv)) {
          sim_res <- importResultsFromCSV(sim, results_csv)
        } else {
          res_list <- runSimulations(simulations = sim)
          sim_res <- res_list[[1]]
        }

        if (!is.null(qpaths)) {
          qpaths <- intersect(qpaths, sim_res$allQuantityPaths)
          if (length(qpaths) == 0) {
            qpaths <- NULL
          }
        }
        if (is.null(qpaths)) {
          qpaths <- sim_res$allQuantityPaths
        }

        plot_error <- NULL
        plot_object <- NULL

        tryCatch({
          dc <- DataCombined$new()
          dc$addSimulationResults(simulationResults = sim_res, quantitiesOrPaths = qpaths, groups = "Simulation")
          plot_object <- plotIndividualTimeProfile(dc)
        }, error = function(e) {
          plot_error <<- conditionMessage(e)
        })

        if (!is.null(plot_object) && has_ggplot) {
          plot_object <- plot_object +
            ggplot2::theme(
              legend.position = "bottom",
              legend.box = "horizontal",
              legend.title = ggplot2::element_blank(),
              legend.text = ggplot2::element_text(size = 8),
              legend.key.width = ggplot2::unit(10, "pt")
            ) +
            ggplot2::guides(color = ggplot2::guide_legend(nrow = 2, byrow = TRUE))
        }

        if (is.null(plot_object)) {
          vals <- getOutputValues(sim_res, quantitiesOrPaths = qpaths)
          df <- as.data.frame(vals$data)
          cn <- colnames(df)
          cn_lower <- tolower(cn)
          time_idx <- which(cn_lower == "time")
          if (length(time_idx) == 0) {
            time_idx <- which(grepl("^time", cn_lower))
          }
          if (length(time_idx) == 0) {
            time_idx <- which(grepl("time", cn_lower))
          }
          time_col <- if (length(time_idx) > 0) cn[[time_idx[[1]]]] else ""
          if (is.null(time_col) || time_col == "") {
            stop("Could not find a Time column in extracted results")
          }
          id_cols <- cn[cn_lower %in% c("individualid", "individual_id")]
          value_cols <- setdiff(cn, c(id_cols, time_col))
          if (length(value_cols) == 0) {
            stop("No value columns found in extracted results")
          }
          long_df <- do.call(rbind, lapply(value_cols, function(cn) {
            data.frame(Time = df[[time_col]], Value = df[[cn]], Quantity = cn, stringsAsFactors = FALSE)
          }))

          if (has_ggplot) {
            plot_object <- ggplot2::ggplot(long_df, ggplot2::aes(x = .data$Time, y = .data$Value, color = .data$Quantity)) +
              ggplot2::geom_line() +
              ggplot2::labs(x = time_col, y = "Value") +
              ggplot2::theme(
                legend.position = "bottom",
                legend.box = "horizontal",
                legend.title = ggplot2::element_blank(),
                legend.text = ggplot2::element_text(size = 8),
                legend.key.width = ggplot2::unit(10, "pt")
              ) +
              ggplot2::guides(color = ggplot2::guide_legend(nrow = 2, byrow = TRUE))
          } else {
            file <- file.path(output_dir, paste0(plot_name, ".png"))
            grDevices::png(file, width = 1000, height = 700)
            on.exit(grDevices::dev.off(), add = TRUE)
            plot(long_df$Time, long_df$Value, type = "l", xlab = time_col, ylab = "Value")
            cat(toJSON(list(ok = TRUE, file = file, warning = plot_error), auto_unbox = TRUE))
            quit(save = "no")
          }
        }

        exportConfiguration <- tlf::ExportConfiguration$new(
          path = output_dir,
          name = plot_name,
          format = file_format,
          width = 12,
          height = 7,
          units = "in",
          dpi = dpi
        )
        file <- exportConfiguration$savePlot(plot_object)
        cat(toJSON(list(ok = TRUE, file = file, warning = plot_error), auto_unbox = TRUE))
        """
    ).strip()

    completed = subprocess.run(
        [
            rscript,
            "-e",
            r_code,
            str(Path(pkml_path).resolve()),
            str(plots_dir.resolve()),
            json.dumps(quantity_paths or []),
            plot_name,
            file_format,
            str(dpi),
            str(csv_file.resolve()) if csv_file else "",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
        env=run_env,
    )

    if completed.returncode != 0:
        return {
            "status": "error",
            "error": "OSPSuite-R plotting failed",
            "stderr": completed.stderr,
            "stdout": completed.stdout,
        }

    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {"raw_stdout": stdout}

    plot_file = payload.get("file")
    plot_path: Path | None = None
    if isinstance(plot_file, str) and plot_file:
        plot_path = Path(plot_file)
        if not plot_path.is_absolute():
            plot_path = (plots_dir / plot_file).resolve()
    else:
        plot_path = (plots_dir / f"{plot_name}.{file_format}").resolve()

    if plot_path is None or not plot_path.exists():
        return {
            "status": "error",
            "error": "Plot was not created on disk",
            "pkml_path": str(Path(pkml_path).resolve()),
            "plots_dir": str(plots_dir.resolve()),
            "expected_plot": str(plot_path) if plot_path else None,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    return {
        "status": "success",
        "engine": "ospsuite-r",
        "pkml_path": str(Path(pkml_path).resolve()),
        "plots_dir": str(plots_dir.resolve()),
        "plot_file": str(plot_path),
        "quantity_paths": quantity_paths or [],
    }


def get_drug_pk_parameters(drug_name: str) -> Dict[str, Any]:
    """
    Provide guidance on finding pharmacokinetic parameters for a drug.

    This is a helper tool that provides information about where to find
    the required PK parameters for PBPK modeling.

    Args:
        drug_name: Name of the drug to look up

    Returns:
        Dict with search suggestions and typical value ranges
    """
    return {
        "drug_name": drug_name,
        "required_parameters": {
            "molecular_weight": {
                "description": "Molecular weight in g/mol",
                "typical_range": "100-1000 for small molecules",
                "search_terms": [f"{drug_name} molecular weight", f"{drug_name} MW g/mol"],
                "sources": ["PubChem", "DrugBank", "ChemSpider"],
            },
            "log_p": {
                "description": "Lipophilicity (partition coefficient)",
                "typical_range": "-2 to +6 (negative = hydrophilic, positive = lipophilic)",
                "search_terms": [f"{drug_name} LogP", f"{drug_name} lipophilicity"],
                "sources": ["DrugBank", "PubChem", "scientific literature"],
            },
            "fraction_unbound": {
                "description": "Fraction unbound in plasma (fu)",
                "typical_range": "0.01 to 1.0 (e.g., 0.1 means 10% unbound, 90% bound)",
                "search_terms": [
                    f"{drug_name} plasma protein binding",
                    f"{drug_name} fraction unbound",
                    f"{drug_name} fu"
                ],
                "sources": ["DrugBank", "clinical pharmacology literature"],
            },
            "solubility_mg_l": {
                "description": "Aqueous solubility at physiological pH",
                "typical_range": "0.001 to 10000 mg/L",
                "search_terms": [
                    f"{drug_name} solubility pH 7.4",
                    f"{drug_name} aqueous solubility"
                ],
                "sources": ["DrugBank", "PubChem", "scientific literature"],
            },
        },
        "recommended_sources": [
            {"name": "DrugBank", "url": "https://go.drugbank.com/"},
            {"name": "PubChem", "url": "https://pubchem.ncbi.nlm.nih.gov/"},
            {"name": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov/"},
        ],
        "hint": f"Search for '{drug_name}' in DrugBank or PubChem to find most of these values. "
                "For fraction unbound, look for 'plasma protein binding' in clinical literature.",
    }
