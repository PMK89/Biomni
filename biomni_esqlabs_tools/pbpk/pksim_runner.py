import os
import re
import subprocess
import locale
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _smart_decode(data: bytes) -> str:
    """Try utf-8 first, then fallback to system encoding, then latin-1."""
    if data is None:
        return ""
    try:
        return data.decode("utf-8")
    except Exception:
        try:
            return data.decode(locale.getpreferredencoding(False) or "cp1252", errors="replace")
        except Exception:
            return data.decode("latin-1", errors="replace")


def _run_list(cmd_list: List[str], timeout_sec: int) -> Tuple[int, str, str]:
    """Run command safely, capture output, decode robustly."""
    proc = subprocess.run(
        cmd_list,
        shell=False,
        capture_output=True,
        text=False,  # binary mode to avoid UnicodeDecodeError
        timeout=timeout_sec,
    )
    out = _smart_decode(proc.stdout or b"")
    err = _smart_decode(proc.stderr or b"")
    return proc.returncode, out.strip(), err.strip()


def _find_project_from_logs(out: str, err: str) -> Optional[str]:
    """Search stdout/stderr for a .pksim5 path mentioned by PK-Sim CLI."""
    text = (out or "") + "\n" + (err or "")
    m = re.search(r"Project saved to '([^']+\.pksim5)", text, re.IGNORECASE)
    if m:
        candidate = m.group(1)
        if Path(candidate).exists():
            return candidate
    # Fallback: any .pksim5 path in logs
    m = re.search(r"([A-Z]:\\[^\r\n]+?\.pksim5)", text, re.IGNORECASE)
    if m:
        candidate = m.group(1)
        if Path(candidate).exists():
            return candidate
    return None


def _recent_pksim_candidate(search_dir: str, since_minutes: int = 10) -> Optional[str]:
    """Return most recent *.pksim5 file in search_dir."""
    p = Path(search_dir)
    if not p.exists():
        return None
    cutoff = datetime.now() - timedelta(minutes=since_minutes)
    candidates = sorted(
        (f for f in p.glob("*.pksim5") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for f in candidates:
        if datetime.fromtimestamp(f.stat().st_mtime) >= cutoff:
            return str(f)
    return str(candidates[0]) if candidates else None


def run_pksim_snapshot(
    snapshot_in: str,
    project_out: str,
    export_pkml: Optional[str] = None,
    sim_name: str = "Minimal Simulation",
    pksim_cli: Optional[str] = None,
    timeout_sec: int = 1800,
    dry_run: bool = False,
    input_mode: str = "auto",  # "auto" | "file" | "folder"
) -> Dict[str, Any]:
    """
    Build a PK-Sim® project from a snapshot folder or file and optionally export PKML.

    Args:
        snapshot_in: Path to snapshot folder or file.
        project_out: Path to project folder (or file name if supported).
        export_pkml: Optional path to desired PKML file (or folder).
        sim_name: Name of the simulation to export.
        pksim_cli: Path to PKSim.CLI.exe (defaults to PKSIM_CLI env or standard install path).
        timeout_sec: Timeout for each CLI command.
        dry_run: If True, return planned commands without executing.
        input_mode: "auto" (try file → folder), "file" (force file input), "folder" (force folder input).
    """
    logs: List[str] = []

    # Resolve CLI
    if pksim_cli is None:
        pksim_cli = os.environ.get("PKSIM_CLI")
    if not pksim_cli:
        pksim_cli = r"C:\Program Files\PK-Sim 12\PKSim.CLI.exe"
    cli_path = Path(pksim_cli)
    if not cli_path.exists():
        raise FileNotFoundError(f"PK-Sim CLI not found: {cli_path}")

    snap_path = Path(snapshot_in)
    if not snap_path.exists():
        raise FileNotFoundError(f"Snapshot input not found: {snap_path}")

    proj_path = Path(project_out)
    (proj_path.parent if proj_path.suffix else proj_path).mkdir(parents=True, exist_ok=True)

    cli = str(cli_path)

    # Build command candidates
    build_cmds: List[List[str]] = []
    if input_mode in {"auto", "file"} and snap_path.is_file():
        build_cmds.append([cli, "snap", "-p", "--input", str(snap_path), "--output", str(proj_path)])
    if input_mode in {"auto", "folder"}:
        folder = str(snap_path if snap_path.is_dir() else snap_path.parent)
        build_cmds.append([cli, "snap", "-p", "--input", folder, "--output", str(proj_path)])

    # Prepare PKML export folder/expected file
    export_folder: Optional[str] = None
    expected_pkml: Optional[Path] = None
    if export_pkml:
        export_path = Path(export_pkml)
        if export_path.suffix.lower() == ".pkml":
            export_folder = str(export_path.parent)
            expected_pkml = export_path
        else:
            export_folder = str(export_path)
            expected_pkml = Path(export_folder) / f"{sim_name}.pkml"
        Path(export_folder).mkdir(parents=True, exist_ok=True)

    if dry_run:
        export_cmd = []
        if export_folder:
            export_cmd = [cli, "export", "-k", "--project", str(proj_path),
                          "--output", export_folder, "--simulations", sim_name]
        return {
            "ok": True,
            "dry_run": True,
            "cli_path": cli,
            "snapshot_in": snapshot_in,
            "project_out": project_out,
            "sim_name": sim_name,
            "input_mode": input_mode,
            "build_commands": [" ".join(c) for c in build_cmds],
            "export_command": " ".join(export_cmd) if export_cmd else None,
            "logs": [],
        }

    # --- Build project ---
    built_project_path: Optional[str] = None
    last_err: Optional[str] = None

    for cmd in build_cmds:
        code, out, err = _run_list(cmd, timeout_sec=timeout_sec)
        logs.extend([f"$ {' '.join(cmd)}", "[stdout]\n"+out if out else "", "[stderr]\n"+err if err else ""])
        if code == 0:
            if proj_path.exists():
                built_project_path = str(proj_path)
                break
            candidate = _find_project_from_logs(out, err)
            if candidate:
                built_project_path = candidate
                break
            fallback = _recent_pksim_candidate(str(proj_path))
            if fallback:
                built_project_path = fallback
                break
            last_err = "Build reported success, but no project file found."
            continue
        msg = (out + "\n" + err).lower()
        if "folder" in msg and "does not exist" in msg:
            last_err = err or out or f"Exit {code}"
            continue
        last_err = err or out or f"Exit {code}"
        break

    if not built_project_path or not Path(built_project_path).exists():
        combined = "\n".join(x for x in logs if x)
        raise RuntimeError(f"PK-Sim project was not created.\nLast error: {last_err}\n--- LOGS ---\n{combined}")

    proj_path_str = built_project_path
    export_used = None
    pkml_exported = False

    # --- Export PKML (PK-Sim 12 syntax) ---
    if export_folder:
        export_cmd = [
            cli, "export",
            "-k",
            "--project", proj_path_str,
            "--output", export_folder,
            "--simulations", sim_name,
        ]
        code, out, err = _run_list(export_cmd, timeout_sec=timeout_sec)
        logs.extend([f"$ {' '.join(export_cmd)}", "[stdout]\n"+out if out else "", "[stderr]\n"+err if err else ""])

        if code == 0:
            produced = sorted(Path(export_folder).glob("*.pkml"), key=lambda p: p.stat().st_mtime, reverse=True)
            if produced:
                chosen = expected_pkml if expected_pkml and expected_pkml.exists() else produced[0]
                if expected_pkml and not expected_pkml.exists():
                    try:
                        chosen.replace(expected_pkml)
                        chosen = expected_pkml
                    except Exception:
                        pass
                export_used = " ".join(export_cmd)
                pkml_exported = True

    return {
        "ok": True,
        "built_project": proj_path_str,
        "created_project": Path(proj_path_str).exists(),
        "pkml_exported": pkml_exported,
        "export_command_used": export_used,
        "cli_path": cli,
        "snapshot_in": snapshot_in,
        "sim_name": sim_name,
        "input_mode": input_mode,
        "logs": [x for x in logs if x],
    }
