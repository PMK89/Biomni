from pathlib import Path
from typing import Optional
import json

def create_drug_snapshot(
    drug_name: str,
    out_path: str,
    data_dir: str = "./data/esqlabs/snapshot_files",
    individual_name: str = "Individual_1",
    formulation_name: str = "Oral IR Formulation",
    protocol_name: str = "Protocol_Main",
) -> dict:
    """
    [DEPRECATED] Legacy tool for creating PK-Sim snapshots.

    IMPORTANT: This tool is deprecated and has known reliability issues.
    Use create_pbpk_snapshot instead, which is simpler and more reliable.

    create_pbpk_snapshot provides:
    - Direct snapshot creation without multi-step orchestration
    - Clear parameter validation with helpful error messages
    - No dependency on example files
    - Guaranteed valid PK-Sim snapshot output

    This legacy tool orchestrates:
    1. Web search for pharmacokinetic properties
    2. Parameter extraction
    3. RAG-based snapshot building (requires example files)

    Args:
        drug_name: Name of the drug/compound (e.g., "Ibuprofen", "Aspirin")
        out_path: Output path for the snapshot JSON file
        data_dir: Directory containing example snapshot files for RAG (default: ./data/esqlabs/snapshot_files)
        individual_name: Name for the individual (default: "Individual_1")
        formulation_name: Name for the formulation (default: "Oral IR Formulation")
        protocol_name: Name for the protocol (default: "Protocol_Main")

    Returns:
        dict with status and instructions for next steps
    """
    # Sanitize out_path: if it starts with /snapshots/ or /data/, make it relative
    # This handles cases where the agent interprets instructions as absolute system paths
    if out_path.startswith("/snapshots/") or out_path.startswith("/data/"):
        out_path = out_path.lstrip("/")

    # Ensure data_dir is absolute or correct relative path
    project_root = Path(__file__).resolve().parents[2]
    if data_dir.startswith("./"):
        data_dir_path = project_root / data_dir[2:]
    elif data_dir.startswith("/"):
        data_dir_path = Path(data_dir)
    else:
        data_dir_path = project_root / data_dir
        
    # Fallback if default doesn't exist, check for common alternatives
    if not data_dir_path.exists():
        alternatives = [
            project_root / "data/esqlabs/snapshot_files",
            project_root / "data/snapshot_files",
        ]
        for alt in alternatives:
            if alt.exists():
                data_dir_path = alt
                break
    
    # Update data_dir string for instructions
    data_dir = str(data_dir_path.resolve())

    # Create the base snapshot file immediately if it doesn't exist
    base_snapshot = {
        "Compounds": [{"Name": drug_name}],
        "Individuals": [{"Name": individual_name}],
        "Formulations": [{"Name": formulation_name}],
        "Protocols": [{"Name": protocol_name}],
        "Version": "1.0"
    }
    
    try:
        # Ensure directory exists
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Write base snapshot
        with open(out_path, 'w') as f:
            json.dump(base_snapshot, f, indent=2)
            
        project_root = Path(__file__).resolve().parents[2]
        repo_snapshots_dir = project_root / "snapshots"
        # Just for display in instructions
        absolute_target = str((repo_snapshots_dir / Path(out_path).name).resolve())
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to create base snapshot: {str(e)}",
            "out_path": out_path
        }

    return {
        "status": "requires_research",
        "drug_name": drug_name,
        "out_path": out_path,
        "data_dir": data_dir,
        "instructions": f"""
To complete this task, you need to:

1. **Search for pharmacokinetic data** for {drug_name}:
   - Molecular weight (MW) in g/mol
   - Lipophilicity (LogP or LogD)
   - Fraction unbound in plasma (Fu)
   - Solubility (preferably at pH 7.4) in mg/L

2. **Use web_search** to find reliable sources:
   - Search: "{drug_name} molecular weight"
   - Search: "{drug_name} LogP lipophilicity"
   - Search: "{drug_name} fraction unbound plasma protein binding"
   - Search: "{drug_name} solubility pH 7.4"

   ✅ For every value include the numeric value, units, and a verifiable URL + short citation in your notes before moving on.

3. **After gathering data**, call rag_json_build with this structure:
```python
from biomni.tool.biomni_tool_json_rag_V2 import rag_json_build

rag_json_build(
    section="Compounds",
    values=[{{
        "Name": "{drug_name}",
        "Parameters": [
            {{"Name": "Molecular weight", "Value": <MW_VALUE>, "Unit": "g/mol"}}
        ],
        "Lipophilicity": [
            {{
                "Name": "Measurement",
                "Parameters": [{{"Name": "Lipophilicity", "Value": <LOGP_VALUE>, "Unit": "Log Units"}}]
            }}
        ],
        "FractionUnbound": [
            {{
                "Name": "Measurement",
                "Species": "Human",
                "Parameters": [{{"Name": "Fraction unbound (plasma, reference value)", "Value": <FU_VALUE>}}]
            }}
        ],
        "Solubility": [
            {{
                "Name": "Assumption",
                "Parameters": [
                    {{"Name": "Solubility at reference pH", "Value": <SOLUBILITY_VALUE>, "Unit": "mg/l"}},
                    {{"Name": "Reference pH", "Value": 7.4}}
                ]
            }}
        ]
    }}],
    out_path="{out_path}",
    data_dir="{data_dir}",
    inherit_rest=True,
    overrides={{
        "Individuals": [{{"Name": "{individual_name}"}}],
        "Formulations": [{{"Name": "{formulation_name}"}}],
        "Protocols": [{{"Name": "{protocol_name}"}}]
    }},
    rebuild_simulations=True
)
```

⚠️ **Do not skip this step. You must actually execute `rag_json_build` once the parameters are populated.**

4. **Snapshot location requirements**
   - The `out_path` above (`{out_path}`) is relative to the repository root and resolves to the absolute file `{absolute_target}`.
   - Confirm in your final response that the snapshot was written to *both* `snapshots/{Path(out_path).name}` (relative) and `{absolute_target}` (absolute path on disk).
   - If the file was not created, continue working until it exists.

**Important notes:**
- Molecular weight: typically 100-1000 g/mol for small molecules
- LogP: typically -2 to +6 (negative = hydrophilic, positive = lipophilic)
- Fraction unbound: value between 0 and 1 (e.g., 0.01 = 1% unbound, 99% bound)
- Solubility: in mg/L at pH 7.4 (physiological pH)

**Completion checklist before responding:**
1. `create_drug_snapshot` (this tool) has been run (already done).
2. PK values + sources have been collected.
3. `rag_json_build` has been executed with those values.
4. `{absolute_target}` exists and contains the final snapshot JSON.
"""
    }