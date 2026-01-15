"""
Structured logging configuration for workflow execution.

Provides:
- Run-specific log files
- Structured JSON logging for machine parsing
- Redaction of sensitive information
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# Patterns for sensitive data that should be redacted
SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key[s]?\s*[=:]\s*)(['\"]?)([a-zA-Z0-9_-]{20,})(\2)", re.IGNORECASE), r"\1\2[REDACTED]\4"),
    (re.compile(r"(bearer\s+)([a-zA-Z0-9_.-]+)", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(token[s]?\s*[=:]\s*)(['\"]?)([a-zA-Z0-9_.-]{20,})(\2)", re.IGNORECASE), r"\1\2[REDACTED]\4"),
    (re.compile(r"(password[s]?\s*[=:]\s*)(['\"]?)([^\s'\"]+)(\2)", re.IGNORECASE), r"\1\2[REDACTED]\4"),
    (re.compile(r"(secret[s]?\s*[=:]\s*)(['\"]?)([a-zA-Z0-9_.-]{10,})(\2)", re.IGNORECASE), r"\1\2[REDACTED]\4"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"xoxb-[a-zA-Z0-9-]+"), "[REDACTED_SLACK_TOKEN]"),
]


def redact_sensitive(message: str) -> str:
    """Redact sensitive information from log messages."""
    for pattern, replacement in SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts sensitive information."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_sensitive(original)


class StructuredLogHandler(logging.Handler):
    """
    Handler that writes structured JSON logs to a file.

    Each log entry includes:
    - timestamp
    - level
    - run_id (if available)
    - step (if available)
    - message
    - extra fields
    """

    def __init__(self, log_file: Path, run_id: str):
        super().__init__()
        self.log_file = log_file
        self.run_id = run_id
        self._file = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "run_id": self.run_id,
                "logger": record.name,
                "message": redact_sensitive(self.format(record)),
            }

            # Add extra fields
            if hasattr(record, "step"):
                entry["step"] = record.step
            if hasattr(record, "duration"):
                entry["duration"] = record.duration
            if hasattr(record, "inputs"):
                entry["inputs"] = record.inputs
            if hasattr(record, "outputs"):
                entry["outputs"] = record.outputs
            if record.exc_info:
                import traceback
                entry["exception"] = "".join(traceback.format_exception(*record.exc_info))

            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

        except Exception:
            self.handleError(record)


class WorkflowLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that includes run_id and step context."""

    def __init__(self, logger: logging.Logger, run_id: str, step: Optional[str] = None):
        super().__init__(logger, {"run_id": run_id, "step": step})
        self.run_id = run_id
        self._current_step = step

    def set_step(self, step: Optional[str]) -> None:
        """Set the current step context."""
        self._current_step = step
        self.extra["step"] = step

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        extra = kwargs.get("extra", {})
        extra["run_id"] = self.run_id
        if self._current_step:
            extra["step"] = self._current_step
        kwargs["extra"] = extra
        return msg, kwargs

    def step_start(self, step: str, inputs: Optional[Dict[str, Any]] = None) -> None:
        """Log step start with inputs."""
        self.set_step(step)
        extra = {"step": step}
        if inputs:
            extra["inputs"] = inputs
        self.info(f"Starting step: {step}", extra=extra)

    def step_complete(self, step: str, duration: float, outputs: Optional[Dict[str, Any]] = None) -> None:
        """Log step completion with outputs."""
        extra = {"step": step, "duration": duration}
        if outputs:
            extra["outputs"] = outputs
        self.info(f"Completed step: {step} ({duration:.2f}s)", extra=extra)

    def step_failed(self, step: str, error: str, duration: Optional[float] = None) -> None:
        """Log step failure."""
        extra = {"step": step}
        if duration:
            extra["duration"] = duration
        self.error(f"Failed step: {step} - {error}", extra=extra)


_workflow_loggers: Dict[str, WorkflowLoggerAdapter] = {}


def setup_workflow_logging(
    run_id: str,
    run_dir: Path,
    log_level: int = logging.INFO,
    console_output: bool = True,
) -> WorkflowLoggerAdapter:
    """
    Set up logging for a workflow run.

    Creates:
    - run_dir/logs/workflow.log (human-readable)
    - run_dir/logs/structured.jsonl (machine-readable)

    Args:
        run_id: Unique identifier for this run
        run_dir: Directory for this run's artifacts
        log_level: Logging level
        console_output: Whether to also log to console

    Returns:
        WorkflowLoggerAdapter configured for this run
    """
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Create logger
    logger_name = f"workflow.{run_id}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)

    # Clear any existing handlers
    logger.handlers.clear()

    # Human-readable file handler
    file_handler = logging.FileHandler(logs_dir / "workflow.log", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_formatter = RedactingFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Structured JSON handler
    json_handler = StructuredLogHandler(logs_dir / "structured.jsonl", run_id)
    json_handler.setLevel(log_level)
    json_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(json_handler)

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_formatter = RedactingFormatter(
            fmt="[%(levelname)s] %(message)s",
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # Create adapter
    adapter = WorkflowLoggerAdapter(logger, run_id)
    _workflow_loggers[run_id] = adapter

    return adapter


def get_run_logger(run_id: str) -> Optional[WorkflowLoggerAdapter]:
    """Get the logger for a specific run."""
    return _workflow_loggers.get(run_id)


def close_workflow_logging(run_id: str) -> None:
    """Close and clean up logging for a run."""
    logger_name = f"workflow.{run_id}"
    logger = logging.getLogger(logger_name)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    _workflow_loggers.pop(run_id, None)
