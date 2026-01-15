#!/usr/bin/env python3
"""
CLI for running PBPK workflows with reliability harness.

Usage:
    # Single run
    python -m biomni_esqlabs_tools.workflow.cli run --drug Bupropion --dose 150

    # Repeated runs for reliability testing
    python -m biomni_esqlabs_tools.workflow.cli test --drug Bupropion --n-runs 10

    # Doctor check
    python -m biomni_esqlabs_tools.workflow.cli doctor
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def cmd_run(args: argparse.Namespace) -> int:
    """Run a single PBPK workflow."""
    from .orchestrator import WorkflowOrchestrator
    from .pbpk_steps import create_pbpk_workflow_steps

    run_dir_base = Path(args.output_dir) if args.output_dir else Path.cwd() / "runs"

    steps = create_pbpk_workflow_steps(
        drug_name=args.drug,
        dose_mg=args.dose,
        molecular_weight=args.mw,
        log_p=args.logp,
        fraction_unbound=args.fu,
        solubility_mg_l=args.sol,
        simulation_duration_h=args.duration,
        download_papers=args.download_papers,
        allow_placeholders=args.allow_placeholders,
    )

    orchestrator = WorkflowOrchestrator(
        workflow_name="pbpk_workflow",
        steps=steps,
        run_dir_base=run_dir_base,
        config={"continue_on_failure": args.continue_on_failure},
    )

    manifest, success = orchestrator.run(
        inputs={
            "drug_name": args.drug,
            "dose_mg": args.dose,
        },
        resume_from=args.resume,
    )

    # Print summary
    print("\n" + "=" * 60)
    print(f"WORKFLOW {'SUCCEEDED' if success else 'FAILED'}")
    print("=" * 60)
    print(f"Run ID: {manifest.run_id}")
    print(f"Run directory: {manifest.run_dir}")
    print(f"Duration: {manifest.total_duration_seconds:.1f}s" if manifest.total_duration_seconds else "")
    print(f"Steps: {manifest.succeeded_count}/{manifest.step_count} succeeded")

    if manifest.failed_count > 0:
        print("\nFailed steps:")
        for name, step in manifest.steps.items():
            if step.status.value == "FAILED":
                print(f"  - {name}: {step.error}")

    return 0 if success else 1


def cmd_test(args: argparse.Namespace) -> int:
    """Run repeated workflow tests for reliability validation."""
    from .orchestrator import WorkflowOrchestrator
    from .pbpk_steps import create_pbpk_workflow_steps

    run_dir_base = Path(args.output_dir) if args.output_dir else Path.cwd() / "runs"

    steps = create_pbpk_workflow_steps(
        drug_name=args.drug,
        dose_mg=args.dose,
        molecular_weight=args.mw,
        log_p=args.logp,
        fraction_unbound=args.fu,
        solubility_mg_l=args.sol,
        simulation_duration_h=args.duration,
        download_papers=False,  # Skip for reliability tests
        allow_placeholders=True,
    )

    print(f"\nRunning {args.n_runs} workflow iterations for reliability testing...")
    print(f"Drug: {args.drug}, Dose: {args.dose}mg")
    print("=" * 60)

    metrics = WorkflowOrchestrator.run_repeated(
        workflow_name="pbpk_workflow",
        steps=steps,
        n_runs=args.n_runs,
        run_dir_base=run_dir_base,
        inputs={"drug_name": args.drug, "dose_mg": args.dose},
    )

    # Print results
    print("\n" + "=" * 60)
    print("RELIABILITY TEST RESULTS")
    print("=" * 60)
    print(f"Total runs: {metrics['n_runs']}")
    print(f"Successes: {metrics['successes']}")
    print(f"Success rate: {metrics['success_rate'] * 100:.1f}%")

    print("\nPer-step success rates:")
    for step, rate in metrics["per_step_success_rates"].items():
        print(f"  {step}: {rate * 100:.1f}%")

    print("\nAverage step durations:")
    for step, duration in metrics["average_durations"].items():
        print(f"  {step}: {duration:.2f}s")

    if metrics["failure_reasons"]:
        print("\nFailure reasons:")
        for failure in metrics["failure_reasons"][:5]:  # Show first 5
            print(f"  Run {failure['run_id']}, step {failure['step']}: {failure['error']}")

    # Save metrics to file
    metrics_path = run_dir_base / "reliability_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"\nMetrics saved to: {metrics_path}")

    # Return success if >= 95% success rate
    target_rate = args.min_success_rate / 100
    if metrics["success_rate"] >= target_rate:
        print(f"\n✓ PASSED: Success rate {metrics['success_rate'] * 100:.1f}% >= {args.min_success_rate}%")
        return 0
    else:
        print(f"\n✗ FAILED: Success rate {metrics['success_rate'] * 100:.1f}% < {args.min_success_rate}%")
        return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check environment and dependencies."""
    print("=" * 60)
    print("VIOMNI/Biomni Environment Doctor")
    print("=" * 60)

    checks: List[tuple[str, bool, str]] = []

    # Check Python version
    py_version = sys.version_info
    checks.append((
        "Python version",
        py_version >= (3, 9),
        f"{py_version.major}.{py_version.minor}.{py_version.micro}",
    ))

    # Check required packages
    required_packages = [
        "biomni",
        "biomni_esqlabs_tools",
        "fastapi",
        "gradio",
    ]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
            checks.append((f"Package: {pkg}", True, "installed"))
        except ImportError:
            checks.append((f"Package: {pkg}", False, "not installed"))

    # Check environment variables
    env_vars = [
        ("OPENAI_API_KEY", True),
        ("BIOMNI_BASE_PATH", False),
        ("BIOMNI_PBPK_ENGINE", False),
        ("PKSIM_CLI", False),
    ]
    for var, required in env_vars:
        value = os.environ.get(var)
        if value:
            # Redact sensitive values
            display = "[SET]" if "KEY" in var or "SECRET" in var else value[:50]
            checks.append((f"Env: {var}", True, display))
        else:
            checks.append((f"Env: {var}", not required, "not set" + (" (optional)" if not required else "")))

    # Check for PK-Sim CLI
    pksim_paths = [
        "/mnt/c/Program Files/PK-Sim 12/PKSim.CLI.exe",
        "/mnt/c/Program Files/PK-Sim 11/PKSim.CLI.exe",
        "C:\\Program Files\\PK-Sim 12\\PKSim.CLI.exe",
    ]
    pksim_found = False
    for path in pksim_paths:
        if os.path.exists(path):
            checks.append(("PK-Sim CLI", True, path))
            pksim_found = True
            break
    if not pksim_found:
        checks.append(("PK-Sim CLI", False, "not found (OSPSuite-R fallback may be used)"))

    # Check for Rscript (OSPSuite-R)
    rscript = shutil.which("Rscript")
    if rscript:
        checks.append(("Rscript", True, rscript))
        # Check for ospsuite package
        try:
            result = subprocess.run(
                [rscript, "-e", "library(ospsuite); cat('ok')"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and "ok" in result.stdout:
                checks.append(("OSPSuite-R", True, "installed"))
            else:
                checks.append(("OSPSuite-R", False, "not installed"))
        except Exception as e:
            checks.append(("OSPSuite-R", False, f"check failed: {e}"))
    else:
        checks.append(("Rscript", False, "not found"))

    # Check writable directories
    test_dirs = [
        Path.cwd() / "runs",
        Path.cwd() / "data",
    ]
    for dir_path in test_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            test_file = dir_path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            checks.append((f"Writable: {dir_path}", True, "ok"))
        except Exception as e:
            checks.append((f"Writable: {dir_path}", False, str(e)))

    # Print results
    all_pass = True
    for name, passed, detail in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {name}: {detail}")
        if not passed and "optional" not in detail.lower():
            all_pass = False

    print()
    if all_pass:
        print("✓ All required checks passed")
        return 0
    else:
        print("✗ Some checks failed")
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PBPK Workflow CLI - Reliable end-to-end pipeline execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a single PBPK workflow")
    run_parser.add_argument("--drug", "-d", required=True, help="Drug name")
    run_parser.add_argument("--dose", type=float, default=100.0, help="Dose in mg")
    run_parser.add_argument("--mw", type=float, help="Molecular weight (g/mol)")
    run_parser.add_argument("--logp", type=float, help="LogP (lipophilicity)")
    run_parser.add_argument("--fu", type=float, help="Fraction unbound (0-1)")
    run_parser.add_argument("--sol", type=float, help="Solubility at pH 7.4 (mg/L)")
    run_parser.add_argument("--duration", type=float, default=24.0, help="Simulation duration (hours)")
    run_parser.add_argument("--output-dir", "-o", help="Output directory for runs")
    run_parser.add_argument("--resume", help="Resume from run ID")
    run_parser.add_argument("--download-papers", action="store_true", help="Download papers for PK research")
    run_parser.add_argument("--allow-placeholders", action="store_true", default=True,
                           help="Allow placeholder values for missing parameters")
    run_parser.add_argument("--continue-on-failure", action="store_true",
                           help="Continue workflow even if a step fails")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run repeated reliability tests")
    test_parser.add_argument("--drug", "-d", default="Bupropion", help="Drug name")
    test_parser.add_argument("--dose", type=float, default=150.0, help="Dose in mg")
    test_parser.add_argument("--mw", type=float, default=239.74, help="Molecular weight")
    test_parser.add_argument("--logp", type=float, default=3.6, help="LogP")
    test_parser.add_argument("--fu", type=float, default=0.16, help="Fraction unbound")
    test_parser.add_argument("--sol", type=float, default=312.0, help="Solubility")
    test_parser.add_argument("--duration", type=float, default=24.0, help="Simulation duration")
    test_parser.add_argument("--n-runs", "-n", type=int, default=10, help="Number of runs")
    test_parser.add_argument("--min-success-rate", type=float, default=95.0,
                           help="Minimum success rate (percent)")
    test_parser.add_argument("--output-dir", "-o", help="Output directory for runs")

    # Doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Check environment and dependencies")

    args = parser.parse_args()

    if args.command == "run":
        return cmd_run(args)
    elif args.command == "test":
        return cmd_test(args)
    elif args.command == "doctor":
        return cmd_doctor(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
