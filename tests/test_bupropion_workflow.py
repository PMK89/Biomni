#!/usr/bin/env python3
"""
Test the complete Bupropion PBPK workflow that the agent should follow.

This demonstrates the correct usage pattern that should replace
the old multi-step workflow.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def test_bupropion_workflow():
    """Test the recommended workflow for creating a Bupropion snapshot."""
    print("=" * 70)
    print("BUPROPION PBPK WORKFLOW TEST")
    print("=" * 70)

    try:
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import (
            get_drug_pk_parameters,
            create_pbpk_snapshot,
        )

        # Step 1: Get parameter guidance
        print("\n[Step 1] Getting parameter guidance for Bupropion...")
        guidance = get_drug_pk_parameters("Bupropion")

        print(f"✓ Found guidance for {guidance['drug_name']}")
        print(f"  Required parameters: {list(guidance['required_parameters'].keys())}")
        print(f"  Recommended sources: {[s['name'] for s in guidance['recommended_sources']]}")

        # Step 2: Create snapshot with known parameters
        # (In real usage, agent would search for these values)
        print("\n[Step 2] Creating PBPK snapshot with Bupropion parameters...")

        # Known Bupropion parameters from DrugBank and literature
        result = create_pbpk_snapshot(
            drug_name="Bupropion",
            dose_mg=150.0,
            molecular_weight=239.74,  # g/mol (PubChem)
            log_p=3.6,  # Lipophilicity (DrugBank)
            fraction_unbound=0.16,  # 16% unbound = 84% protein bound (DailyMed)
            solubility_mg_l=312.0,  # mg/L at pH 7.4 (literature)
            reference_ph=7.4,
            individual_name="HealthyAdult",
            population="European_ICRP_2002",
            age_years=30.0,
            weight_kg=70.0,
            height_cm=175.0,
            simulation_duration_h=72.0,
            out_path=str(project_root / "tests" / "bupropion_150mg_snapshot.json"),
        )

        print(f"Status: {result['status']}")

        if result["status"] == "success":
            print(f"✓ Snapshot created successfully!")
            print(f"  File: {result['file_path']}")
            print(f"  File exists: {result['file_exists']}")
            print(f"  Drug: {result['drug_name']}")
            print(f"  Dose: {result['dose_mg']} mg")
            print(f"\n  Parameters used:")
            for param, value in result["parameters"].items():
                print(f"    - {param}: {value}")

            # Verify the file contents
            import json

            with open(result["file_path"], "r") as f:
                snapshot = json.load(f)

            print(f"\n  Snapshot validation:")
            print(f"    - Version: {snapshot.get('Version')}")
            print(f"    - Compounds: {len(snapshot.get('Compounds', []))}")
            print(f"    - Individuals: {len(snapshot.get('Individuals', []))}")
            print(f"    - Formulations: {len(snapshot.get('Formulations', []))}")
            print(f"    - Protocols: {len(snapshot.get('Protocols', []))}")
            print(f"    - Simulations: {len(snapshot.get('Simulations', []))}")

            if snapshot.get("Simulations"):
                sim = snapshot["Simulations"][0]
                print(f"\n  Simulation details:")
                print(f"    - Name: {sim.get('Name')}")
                print(f"    - Model: {sim.get('Model')}")
                print(f"    - Individual: {sim.get('Individual')}")

            print(f"\n{result.get('next_step')}")

            return True
        else:
            print(f"✗ Snapshot creation failed!")
            print(f"  Error: {result.get('error')}")
            if "hint" in result:
                print(f"  Hint: {result['hint']}")
            if "missing_parameters" in result:
                print(f"  Missing: {result['missing_parameters']}")
            return False

    except Exception as e:
        print(f"\n✗ Test failed with exception: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def show_agent_instructions():
    """Show the instructions that should be given to the agent."""
    print("\n" + "=" * 70)
    print("AGENT INSTRUCTIONS")
    print("=" * 70)
    print("""
When asked to create a PBPK simulation, follow this workflow:

1. Get parameter guidance:
   get_drug_pk_parameters("DrugName")

2. Search for PK parameters (molecular_weight, log_p, fraction_unbound, solubility_mg_l)
   - Use web search for "DrugName DrugBank" or "DrugName PubChem"
   - Look for clinical pharmacology information

3. Create snapshot using create_pbpk_snapshot:
   create_pbpk_snapshot(
       drug_name="DrugName",
       dose_mg=<dose>,
       molecular_weight=<MW>,
       log_p=<LogP>,
       fraction_unbound=<fu>,
       solubility_mg_l=<sol>
   )

4. If PK-Sim is available, run simulation:
   run_pbpk_simulation(snapshot_path="<path>")

DO NOT USE:
- create_drug_snapshot (deprecated, complex)
- rag_json_build (deprecated, requires example files)
""")


if __name__ == "__main__":
    success = test_bupropion_workflow()
    show_agent_instructions()

    print("\n" + "=" * 70)
    if success:
        print("✓ WORKFLOW TEST PASSED")
        print("=" * 70)
        sys.exit(0)
    else:
        print("✗ WORKFLOW TEST FAILED")
        print("=" * 70)
        sys.exit(1)
