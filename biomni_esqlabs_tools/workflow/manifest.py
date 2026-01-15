"""
Run manifest for tracking workflow execution state.

Provides persistent, resumable tracking of:
- Per-step status (NOT_STARTED, RUNNING, SUCCEEDED, FAILED, SKIPPED)
- Inputs, outputs, checksums, timestamps
- Tool versions and environment info
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class StepStatus(str, Enum):
    """Status of a workflow step."""
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class StepRecord:
    """Record of a single workflow step execution."""
    name: str
    status: StepStatus = StepStatus.NOT_STARTED
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    output_checksums: Dict[str, str] = field(default_factory=dict)
    validation_results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_traceback: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepRecord":
        """Create from dictionary."""
        data = data.copy()
        data["status"] = StepStatus(data.get("status", "NOT_STARTED"))
        return cls(**data)


def _get_git_sha() -> Optional[str]:
    """Get current git commit SHA if available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent.parent.parent,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return None


def _get_sanitized_env() -> Dict[str, str]:
    """Get environment variables with secrets redacted."""
    sensitive_patterns = [
        "KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH",
        "API_KEY", "PRIVATE", "CERT", "PEM",
    ]
    env = {}
    for key, value in os.environ.items():
        if any(pattern in key.upper() for pattern in sensitive_patterns):
            env[key] = "[REDACTED]"
        else:
            env[key] = value
    return env


def compute_file_checksum(path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    if not path.exists():
        return ""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]


@dataclass
class RunManifest:
    """
    Persistent manifest tracking the state of a workflow run.

    Enables:
    - Resume from partial runs
    - Verification of step completion
    - Audit trail of all operations
    """
    run_id: str
    run_dir: Path
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str = "NOT_STARTED"
    steps: Dict[str, StepRecord] = field(default_factory=dict)

    # Metadata
    git_sha: Optional[str] = field(default_factory=_get_git_sha)
    python_version: str = field(default_factory=lambda: sys.version)
    tool_versions: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)

    # Workflow config
    workflow_name: str = ""
    workflow_config: Dict[str, Any] = field(default_factory=dict)

    # Summary
    total_duration_seconds: Optional[float] = None
    step_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0

    _manifest_path: Optional[Path] = field(default=None, repr=False)

    def __post_init__(self):
        if isinstance(self.run_dir, str):
            self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.run_dir / "manifest.json"

        # Capture sanitized environment on creation
        if not self.environment:
            self.environment = _get_sanitized_env()

    def add_step(self, name: str) -> StepRecord:
        """Add a new step to track."""
        if name not in self.steps:
            self.steps[name] = StepRecord(name=name)
            self.step_count = len(self.steps)
        return self.steps[name]

    def get_step(self, name: str) -> Optional[StepRecord]:
        """Get a step record by name."""
        return self.steps.get(name)

    def start_step(self, name: str, inputs: Optional[Dict[str, Any]] = None) -> StepRecord:
        """Mark a step as started."""
        step = self.add_step(name)
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(timezone.utc).isoformat()
        if inputs:
            step.inputs = inputs
        self.save()
        return step

    def complete_step(
        self,
        name: str,
        outputs: Optional[Dict[str, Any]] = None,
        validation_results: Optional[Dict[str, Any]] = None,
        output_files: Optional[List[Path]] = None,
    ) -> StepRecord:
        """Mark a step as completed successfully."""
        step = self.steps.get(name)
        if not step:
            raise ValueError(f"Step {name} not found in manifest")

        step.status = StepStatus.SUCCEEDED
        step.completed_at = datetime.now(timezone.utc).isoformat()

        if step.started_at:
            started = datetime.fromisoformat(step.started_at.replace("Z", "+00:00"))
            completed = datetime.fromisoformat(step.completed_at.replace("Z", "+00:00"))
            step.duration_seconds = (completed - started).total_seconds()

        if outputs:
            step.outputs = outputs
        if validation_results:
            step.validation_results = validation_results
        if output_files:
            step.output_checksums = {
                str(p): compute_file_checksum(p) for p in output_files
            }

        self._update_counts()
        self.save()
        return step

    def fail_step(
        self,
        name: str,
        error: str,
        error_traceback: Optional[str] = None,
    ) -> StepRecord:
        """Mark a step as failed."""
        step = self.steps.get(name)
        if not step:
            raise ValueError(f"Step {name} not found in manifest")

        step.status = StepStatus.FAILED
        step.completed_at = datetime.now(timezone.utc).isoformat()
        step.error = error
        step.error_traceback = error_traceback

        if step.started_at:
            started = datetime.fromisoformat(step.started_at.replace("Z", "+00:00"))
            completed = datetime.fromisoformat(step.completed_at.replace("Z", "+00:00"))
            step.duration_seconds = (completed - started).total_seconds()

        self._update_counts()
        self.save()
        return step

    def skip_step(self, name: str, reason: str = "") -> StepRecord:
        """Mark a step as skipped."""
        step = self.add_step(name)
        step.status = StepStatus.SKIPPED
        step.completed_at = datetime.now(timezone.utc).isoformat()
        step.outputs = {"skip_reason": reason}
        self._update_counts()
        self.save()
        return step

    def start_run(self) -> None:
        """Mark the run as started."""
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "RUNNING"
        self.save()

    def complete_run(self, success: bool = True) -> None:
        """Mark the run as completed."""
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.status = "SUCCEEDED" if success else "FAILED"

        if self.started_at:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            completed = datetime.fromisoformat(self.completed_at.replace("Z", "+00:00"))
            self.total_duration_seconds = (completed - started).total_seconds()

        self._update_counts()
        self.save()

    def _update_counts(self) -> None:
        """Update step counts."""
        self.step_count = len(self.steps)
        self.succeeded_count = sum(1 for s in self.steps.values() if s.status == StepStatus.SUCCEEDED)
        self.failed_count = sum(1 for s in self.steps.values() if s.status == StepStatus.FAILED)
        self.skipped_count = sum(1 for s in self.steps.values() if s.status == StepStatus.SKIPPED)

    def is_step_completed(self, name: str) -> bool:
        """Check if a step has completed successfully."""
        step = self.steps.get(name)
        return step is not None and step.status == StepStatus.SUCCEEDED

    def is_resumable(self) -> bool:
        """Check if the run can be resumed (has incomplete steps)."""
        if self.status == "SUCCEEDED":
            return False
        return any(
            s.status in (StepStatus.NOT_STARTED, StepStatus.RUNNING, StepStatus.FAILED)
            for s in self.steps.values()
        )

    def get_incomplete_steps(self) -> List[str]:
        """Get names of steps that haven't completed successfully."""
        return [
            name for name, step in self.steps.items()
            if step.status not in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
            "git_sha": self.git_sha,
            "python_version": self.python_version,
            "tool_versions": self.tool_versions,
            "environment": self.environment,
            "workflow_name": self.workflow_name,
            "workflow_config": self.workflow_config,
            "total_duration_seconds": self.total_duration_seconds,
            "step_count": self.step_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
        }

    def save(self) -> None:
        """Save manifest to disk."""
        if self._manifest_path:
            with open(self._manifest_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, run_dir: Path) -> Optional["RunManifest"]:
        """Load manifest from disk if it exists."""
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        manifest = cls(
            run_id=data["run_id"],
            run_dir=Path(data["run_dir"]),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            status=data.get("status", "NOT_STARTED"),
            git_sha=data.get("git_sha"),
            python_version=data.get("python_version", ""),
            tool_versions=data.get("tool_versions", {}),
            environment=data.get("environment", {}),
            workflow_name=data.get("workflow_name", ""),
            workflow_config=data.get("workflow_config", {}),
            total_duration_seconds=data.get("total_duration_seconds"),
            step_count=data.get("step_count", 0),
            succeeded_count=data.get("succeeded_count", 0),
            failed_count=data.get("failed_count", 0),
            skipped_count=data.get("skipped_count", 0),
        )

        for name, step_data in data.get("steps", {}).items():
            manifest.steps[name] = StepRecord.from_dict(step_data)

        manifest._manifest_path = manifest_path
        return manifest

    def generate_summary(self) -> Dict[str, Any]:
        """Generate a summary of the run suitable for summary.json."""
        step_summaries = []
        for name, step in self.steps.items():
            step_summaries.append({
                "name": name,
                "status": step.status.value,
                "duration_seconds": step.duration_seconds,
                "error": step.error,
            })

        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_duration_seconds": self.total_duration_seconds,
            "step_count": self.step_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "steps": step_summaries,
            "git_sha": self.git_sha,
        }

    def save_summary(self) -> Path:
        """Save a summary.json file alongside the manifest."""
        summary_path = self.run_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.generate_summary(), f, indent=2, ensure_ascii=False)
        return summary_path
