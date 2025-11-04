def create_drug_snapshot_guided(
    drug_name: str,
    out_path: str,
    data_dir: str = "./data/snapshot_files",
) -> dict:
    """
    Guided tool that provides step-by-step instructions for creating a drug snapshot.
    
    Returns a structured workflow that the agent should follow.
    """
    return {
        "status": "workflow_started",
        "drug_name": drug_name,
        "workflow": [
            {
                "step": 1,
                "action": "search_molecular_weight",
                "query": f"{drug_name} molecular weight g/mol",
                "expected_format": "number between 100-1000",
                "example": "206.28"
            },
            {
                "step": 2,
                "action": "search_lipophilicity",
                "query": f"{drug_name} LogP lipophilicity partition coefficient",
                "expected_format": "number between -2 and 6",
                "example": "3.97"
            },
            {
                "step": 3,
                "action": "search_protein_binding",
                "query": f"{drug_name} plasma protein binding fraction unbound",
                "expected_format": "percentage converted to decimal (0-1)",
                "example": "0.01 for 99% bound",
                "note": "If given as % bound, convert: Fu = (100 - % bound) / 100"
            },
            {
                "step": 4,
                "action": "search_solubility",
                "query": f"{drug_name} aqueous solubility mg/L pH 7.4",
                "expected_format": "number in mg/L",
                "example": "21.0",
                "note": "May need unit conversion (mg/mL → mg/L: multiply by 1000)"
            }
        ],
        "next_action": f"Use web_search for each step above, then call rag_json_build with the collected data"
    }