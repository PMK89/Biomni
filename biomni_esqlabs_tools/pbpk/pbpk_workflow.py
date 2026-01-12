"""
PBPK Workflow Tools - Reliable snapshot creation and simulation running.

These tools provide more deterministic snapshot creation and simulation
execution compared to the multi-step orchestration approach.
"""
from __future__ import annotations

import json
import os
import subprocess
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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

    if missing_params:
        return {
            "status": "error",
            "error": f"Missing required PK parameters: {', '.join(missing_params)}",
            "hint": "Please provide values for all required pharmacokinetic parameters. "
                    "Search for these values in scientific literature or databases like DrugBank.",
            "missing_parameters": missing_params,
        }

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
        # Use current working directory with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = drug_name.lower().replace(" ", "_").replace("-", "_")
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

    if pksim_cli_path is None or not os.path.exists(pksim_cli_path):
        return {
            "status": "error",
            "error": "PK-Sim CLI not found",
            "hint": "Please install PK-Sim or set the PKSIM_CLI environment variable to the path of PKSim.CLI.exe",
            "checked_paths": common_paths if 'common_paths' in dir() else [],
        }

    # Determine output directory
    if output_dir is None:
        output_dir = str(snapshot_file.parent)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

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
