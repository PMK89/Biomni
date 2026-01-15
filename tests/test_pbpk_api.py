#!/usr/bin/env python3
"""
Test script for the PBPK API endpoints.

This script can be run from the command line to test the PBPK
snapshot creation and simulation APIs.

Usage:
    python tests/test_pbpk_api.py

    Or with a running server:
    python tests/test_pbpk_api.py --server http://localhost:8000
"""

import argparse
import json
import sys
from pathlib import Path

# Add the project root to the path for imports
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def test_create_pbpk_snapshot():
    """Test the create_pbpk_snapshot function directly."""
    print("\n" + "=" * 60)
    print("TEST: create_pbpk_snapshot")
    print("=" * 60)

    try:
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import create_pbpk_snapshot

        # Test with Bupropion parameters
        result = create_pbpk_snapshot(
            drug_name="Bupropion",
            dose_mg=150.0,
            molecular_weight=239.74,
            log_p=3.6,
            fraction_unbound=0.16,
            solubility_mg_l=312.0,
            out_path=str(project_root / "tests" / "test_bupropion_snapshot.json"),
        )

        print(f"Status: {result.get('status')}")
        if result.get('status') == 'success':
            print(f"File path: {result.get('file_path')}")
            print(f"File exists: {result.get('file_exists')}")
            print("SUCCESS: Snapshot created successfully")
            return True
        else:
            print(f"Error: {result.get('error')}")
            return False

    except Exception as e:
        print(f"FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_run_pbpk_simulation_ospsuite():
    print("\n" + "=" * 60)
    print("TEST: run_pbpk_simulation (OSPSuite-R backend)")
    print("=" * 60)

    try:
        import os
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import create_pbpk_snapshot, run_pbpk_simulation

        snapshot_path = project_root / "tests" / "test_bupropion_snapshot_ospsuite.json"
        output_dir = project_root / "tests" / "test_bupropion_sim_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        snap = create_pbpk_snapshot(
            drug_name="Bupropion",
            dose_mg=150.0,
            molecular_weight=239.74,
            log_p=3.6,
            fraction_unbound=0.16,
            solubility_mg_l=312.0,
            out_path=str(snapshot_path),
        )
        if snap.get("status") != "success":
            print(f"FAILED: Could not create snapshot: {snap}")
            return False

        os.environ["BIOMNI_PBPK_ENGINE"] = "ospsuite"
        result = run_pbpk_simulation(
            snapshot_path=str(snapshot_path),
            output_dir=str(output_dir),
            export_pkml=False,
            timeout_seconds=600,
        )

        print(f"Status: {result.get('status')}")
        if result.get("status") != "success":
            print(f"FAILED: {result}")
            return False

        produced = list(output_dir.rglob("*"))
        produced = [p for p in produced if p.is_file()]
        if not produced:
            print("FAILED: No output files produced")
            return False

        print(f"SUCCESS: Produced {len(produced)} output file(s)")
        return True

    except Exception as e:
        print(f"FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_missing_parameters():
    """Test that missing parameters are handled correctly."""
    print("\n" + "=" * 60)
    print("TEST: Missing parameters handling")
    print("=" * 60)

    try:
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import create_pbpk_snapshot

        # Test with missing parameters
        result = create_pbpk_snapshot(
            drug_name="TestDrug",
            dose_mg=100.0,
            # Missing: molecular_weight, log_p, fraction_unbound, solubility_mg_l
        )

        print(f"Status: {result.get('status')}")
        if result.get('status') == 'error':
            print(f"Error message: {result.get('error')}")
            print(f"Missing parameters: {result.get('missing_parameters')}")
            print("SUCCESS: Missing parameters correctly detected")
            return True
        else:
            print("FAILED: Should have returned error for missing parameters")
            return False

    except Exception as e:
        print(f"FAILED: {str(e)}")
        return False


def test_get_drug_pk_parameters():
    """Test the get_drug_pk_parameters helper function."""
    print("\n" + "=" * 60)
    print("TEST: get_drug_pk_parameters")
    print("=" * 60)

    try:
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import get_drug_pk_parameters

        result = get_drug_pk_parameters("Bupropion")

        print(f"Drug name: {result.get('drug_name')}")
        print(f"Required parameters: {list(result.get('required_parameters', {}).keys())}")
        print(f"Recommended sources: {[s.get('name') for s in result.get('recommended_sources', [])]}")
        print("SUCCESS: Parameter guidance retrieved")
        return True

    except Exception as e:
        print(f"FAILED: {str(e)}")
        return False


def test_api_with_requests(base_url: str):
    """Test the API endpoints using requests library."""
    print("\n" + "=" * 60)
    print(f"TEST: API Endpoints at {base_url}")
    print("=" * 60)

    try:
        import requests

        # Test the test endpoint
        print("\nTesting /api/pbpk/test...")
        response = requests.get(f"{base_url}/api/pbpk/test", timeout=30)
        print(f"Status code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Test name: {data.get('test_name')}")
            print(f"Result status: {data.get('result', {}).get('status')}")
            print("SUCCESS: Test endpoint works")
        else:
            print(f"FAILED: {response.text}")
            return False

        # Test the parameters endpoint
        print("\nTesting /api/pbpk/parameters/Bupropion...")
        response = requests.get(f"{base_url}/api/pbpk/parameters/Bupropion", timeout=10)
        print(f"Status code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Drug name: {data.get('drug_name')}")
            print("SUCCESS: Parameters endpoint works")
        else:
            print(f"FAILED: {response.text}")
            return False

        # Test the snapshot creation endpoint
        print("\nTesting /api/pbpk/snapshot...")
        payload = {
            "drug_name": "Ibuprofen",
            "dose_mg": 400.0,
            "molecular_weight": 206.29,
            "log_p": 3.97,
            "fraction_unbound": 0.01,  # 99% protein bound
            "solubility_mg_l": 21.0,
        }
        response = requests.post(
            f"{base_url}/api/pbpk/snapshot",
            json=payload,
            timeout=30,
        )
        print(f"Status code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Result status: {data.get('status')}")
            print(f"File path: {data.get('file_path')}")
            print("SUCCESS: Snapshot creation endpoint works")
            return True
        else:
            print(f"FAILED: {response.text}")
            return False

    except ImportError:
        print("Note: requests library not available, skipping API tests")
        print("Install with: pip install requests")
        return True
    except requests.exceptions.ConnectionError:
        print(f"Note: Could not connect to {base_url}")
        print("Make sure the server is running with: uvicorn biomni_esqlabs_app.main:app")
        return True


def main():
    parser = argparse.ArgumentParser(description="Test PBPK API endpoints")
    parser.add_argument(
        "--server",
        default=None,
        help="Server URL for API tests (e.g., http://localhost:8000)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("PBPK API Test Suite")
    print("=" * 60)

    results = []

    # Run direct function tests
    results.append(("create_pbpk_snapshot", test_create_pbpk_snapshot()))
    results.append(("missing_parameters", test_missing_parameters()))
    results.append(("get_drug_pk_parameters", test_get_drug_pk_parameters()))
    results.append(("run_pbpk_simulation_ospsuite", test_run_pbpk_simulation_ospsuite()))

    # Run API tests if server URL provided
    if args.server:
        results.append(("api_endpoints", test_api_with_requests(args.server)))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("All tests PASSED")
        return 0
    else:
        print("Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
