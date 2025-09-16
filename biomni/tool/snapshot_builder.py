# custom_tools/snapshot_builder.py
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional, Tuple

def build_snapshot_file(
    out_path: str,
    version: int = 74,
    individuals: Optional[List[Dict[str, Any]]] = None,
    populations: Optional[List[Dict[str, Any]]] = None,
    compounds: Optional[List[Dict[str, Any]]] = None,
    protocols: Optional[List[Dict[str, Any]]] = None,
    simulations: Optional[List[Dict[str, Any]]] = None,
    pretty: bool = True,
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    """
    Build and save a PK-Sim®/MoBi® snapshot JSON file from provided components.

    Args:
        out_path: Target path for the UTF-8 JSON snapshot (e.g., "snapshots/ibuprofen_snapshot.json").
        version: Snapshot version integer (e.g., 74 for OSP v12.0).
        individuals: List of individual definitions (dicts). See manual for fields.
        populations: List of population definitions (dicts).
        compounds: List of compound definitions (dicts).
        protocols: List of protocol definitions (dicts).
        simulations: List of simulation definitions (dicts).
        pretty: If True, write human-readable JSON (indent=2). Otherwise compact JSON.
        fail_on_warnings: If True, raise an error if validation warnings are detected.

    Returns:
        A dict with:
        - ok: bool
        - out_path: the file path written
        - version: the snapshot version used
        - counts: number of items in each section
        - warnings: list of human-readable validation warnings (empty if none)

    Raises:
        ValueError: if out_path is empty or version invalid, or when fail_on_warnings=True and warnings exist.
        OSError: for filesystem write errors.
    """
    # ----- defaults -----
    individuals = individuals or []
    populations = populations or []
    compounds = compounds or []
    protocols = protocols or []
    simulations = simulations or []

    # ----- basic validations -----
    warnings: List[str] = []
    if not out_path or not isinstance(out_path, str):
        raise ValueError("Parameter 'out_path' must be a non-empty string.")
    if not isinstance(version, int) or version <= 0:
        raise ValueError("Parameter 'version' must be a positive integer.")

    # validate sections are lists of dict
    for name, value in [
        ("individuals", individuals),
        ("populations", populations),
        ("compounds", compounds),
        ("protocols", protocols),
        ("simulations", simulations),
    ]:
        if not isinstance(value, list):
            raise ValueError(f"Section '{name}' must be a list.")
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"Section '{name}' item {i} must be a dict.")

    # ----- domain-specific light validation with gentle warnings -----
    def _warn(msg: str) -> None:
        warnings.append(msg)

    # Individuals
    for i, ind in enumerate(individuals):
        if "Name" not in ind:
            _warn(f"Individuals[{i}] is missing 'Name'.")
        if "Sex" in ind and ind["Sex"] not in ("Male", "Female"):
            _warn(f"Individuals[{i}].Sex should be 'Male' or 'Female'. Got: {ind['Sex']!r}")
        for k in ("Age", "Weight", "Height", "BMI"):
            if k in ind and not isinstance(ind[k], (int, float)):
                _warn(f"Individuals[{i}].{k} should be numeric.")

    # Populations
    for i, pop in enumerate(populations):
        if "Name" not in pop:
            _warn(f"Populations[{i}] is missing 'Name'.")
        if "Size" in pop and (not isinstance(pop["Size"], int) or pop["Size"] <= 0):
            _warn(f"Populations[{i}].Size should be a positive integer.")
        if "SexRatio" in pop and not isinstance(pop["SexRatio"], dict):
            _warn(f"Populations[{i}].SexRatio should be an object like {{'Male': 0.5, 'Female': 0.5}}.")

    # Compounds (very light checks; schema varies per project)
    for i, cmpd in enumerate(compounds):
        if "Name" not in cmpd:
            _warn(f"Compounds[{i}] is missing 'Name'.")
        for k in ("MolecularWeight", "LogP", "FractionUnbound"):
            if k in cmpd and not isinstance(cmpd[k], (int, float)):
                _warn(f"Compounds[{i}].{k} should be numeric.")
        if "Solubility" in cmpd and not isinstance(cmpd["Solubility"], dict):
            _warn(f"Compounds[{i}].Solubility should be an object like {{'Value': 0.01, 'Unit': 'mg/mL'}}.")

    # Protocols
    allowed_types = {"Bolus", "Oral", "Infusion"}
    allowed_routes = {"Intravenous", "Oral", "Subcutaneous"}
    for i, p in enumerate(protocols):
        if "Name" not in p:
            _warn(f"Protocols[{i}] is missing 'Name'.")
        if "Type" in p and p["Type"] not in allowed_types:
            _warn(f"Protocols[{i}].Type should be one of {sorted(allowed_types)}.")
        if "Route" in p and p["Route"] not in allowed_routes:
            _warn(f"Protocols[{i}].Route should be one of {sorted(allowed_routes)}.")

    # Simulations
    for i, sim in enumerate(simulations):
        for req in ("Name",):
            if req not in sim:
                _warn(f"Simulations[{i}] is missing '{req}'.")
        if "Outputs" in sim and not isinstance(sim["Outputs"], list):
            _warn(f"Simulations[{i}].Outputs should be a list of strings.")

    if fail_on_warnings and warnings:
        raise ValueError("Validation warnings present:\n- " + "\n- ".join(warnings))

    # ----- build snapshot object -----
    snapshot = {
        "Version": version,
        "Individuals": individuals,
        "Populations": populations,
        "Compounds": compounds,
        "Protocols": protocols,
        "Simulations": simulations,
    }

    # ----- write file (UTF-8) -----
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        else:
            json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))

    return {
        "ok": True,
        "out_path": out_path,
        "version": version,
        "counts": {
            "Individuals": len(individuals),
            "Populations": len(populations),
            "Compounds": len(compounds),
            "Protocols": len(protocols),
            "Simulations": len(simulations),
        },
        "warnings": warnings,
    }
