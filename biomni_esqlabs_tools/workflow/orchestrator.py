"""
Workflow Orchestrator - State machine for end-to-end workflow execution.

Provides:
- Explicit step sequencing with dependency management
- Validation before and after each step
- Retry with exponential backoff for network operations
- Idempotent step execution (skip if already completed)
- Resume from partial runs
"""

from __future__ import annotations

import time
import traceback
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

from .manifest import RunManifest, StepRecord, StepStatus, compute_file_checksum
from .logging_config import setup_workflow_logging, close_workflow_logging, WorkflowLoggerAdapter


T = TypeVar("T")


class RetryPolicy(Enum):
    """Retry policy for steps."""
    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


@dataclass
class RetryConfig:
    """Configuration for step retries."""
    policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    multiplier: float = 2.0

    def get_delay(self, attempt: int) -> float:
        """Get delay for a given attempt number (0-indexed)."""
        if self.policy == RetryPolicy.NONE or attempt == 0:
            return 0
        if self.policy == RetryPolicy.FIXED:
            return self.initial_delay_seconds
        # Exponential backoff
        delay = self.initial_delay_seconds * (self.multiplier ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass
class StepResult(Generic[T]):
    """Result of a step execution."""
    success: bool
    value: Optional[T] = None
    error: Optional[str] = None
    error_traceback: Optional[str] = None
    outputs: Dict[str, Any] = field(default_factory=dict)
    output_files: List[Path] = field(default_factory=list)
    validation_results: Dict[str, Any] = field(default_factory=dict)


class WorkflowStep(ABC):
    """
    Abstract base class for workflow steps.

    Each step must implement:
    - execute(): The main step logic
    - validate_preconditions(): Check if step can run
    - validate_postconditions(): Check if step succeeded
    """

    name: str = "unnamed_step"
    description: str = ""
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    timeout_seconds: Optional[float] = None
    is_network_operation: bool = False

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None,
        timeout_seconds: Optional[float] = None,
        is_network_operation: bool = False,
    ):
        if name:
            self.name = name
        if description:
            self.description = description
        if retry_config:
            self.retry_config = retry_config
        else:
            self.retry_config = RetryConfig()
        if timeout_seconds:
            self.timeout_seconds = timeout_seconds
        self.is_network_operation = is_network_operation

    @abstractmethod
    def execute(self, context: "WorkflowContext") -> StepResult:
        """
        Execute the step logic.

        Args:
            context: Workflow context with inputs, manifest, logger

        Returns:
            StepResult with success status and outputs
        """
        pass

    def validate_preconditions(self, context: "WorkflowContext") -> tuple[bool, str]:
        """
        Validate that preconditions are met before running.

        Returns:
            Tuple of (valid, error_message)
        """
        return True, ""

    def validate_postconditions(self, context: "WorkflowContext", result: StepResult) -> tuple[bool, str]:
        """
        Validate that step completed successfully.

        Returns:
            Tuple of (valid, error_message)
        """
        return result.success, result.error or ""

    def is_idempotent_complete(self, context: "WorkflowContext") -> bool:
        """
        Check if step has already completed and doesn't need to run again.

        Override this to implement idempotency checks (e.g., output files exist).
        """
        return False


@dataclass
class WorkflowContext:
    """Context passed to each workflow step."""
    run_id: str
    run_dir: Path
    manifest: RunManifest
    logger: WorkflowLoggerAdapter
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)

    def get_step_output(self, step_name: str, key: str) -> Optional[Any]:
        """Get an output from a previous step."""
        step = self.manifest.get_step(step_name)
        if step and step.status == StepStatus.SUCCEEDED:
            return step.outputs.get(key)
        return None

    def set_output(self, key: str, value: Any) -> None:
        """Set an output for the current run."""
        self.outputs[key] = value


class WorkflowOrchestrator:
    """
    Orchestrates execution of workflow steps with:
    - Dependency ordering
    - Retry logic
    - Idempotency
    - Structured logging
    - Manifest tracking
    """

    def __init__(
        self,
        workflow_name: str,
        steps: List[WorkflowStep],
        run_dir_base: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.workflow_name = workflow_name
        self.steps = steps
        self.run_dir_base = run_dir_base or Path.cwd() / "runs"
        self.config = config or {}

    def create_run_id(self) -> str:
        """Create a unique run ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique = uuid.uuid4().hex[:8]
        return f"{timestamp}_{unique}"

    def create_run_dir(self, run_id: str) -> Path:
        """Create a directory for this run."""
        run_dir = self.run_dir_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "logs").mkdir(exist_ok=True)
        return run_dir

    def run(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        resume_from: Optional[str] = None,
    ) -> tuple[RunManifest, bool]:
        """
        Execute the workflow.

        Args:
            inputs: Input parameters for the workflow
            run_id: Optional specific run ID (auto-generated if not provided)
            resume_from: Optional run ID to resume from

        Returns:
            Tuple of (manifest, success)
        """
        # Resume or create new run
        if resume_from:
            resume_dir = self.run_dir_base / resume_from
            manifest = RunManifest.load(resume_dir)
            if not manifest:
                raise ValueError(f"Cannot resume: no manifest found at {resume_dir}")
            run_id = resume_from
            run_dir = resume_dir
        else:
            run_id = run_id or self.create_run_id()
            run_dir = self.create_run_dir(run_id)
            manifest = RunManifest(
                run_id=run_id,
                run_dir=run_dir,
                workflow_name=self.workflow_name,
                workflow_config=self.config,
            )

        # Set up logging
        logger = setup_workflow_logging(run_id, run_dir)

        # Create context
        context = WorkflowContext(
            run_id=run_id,
            run_dir=run_dir,
            manifest=manifest,
            logger=logger,
            inputs=inputs or {},
            config=self.config,
        )

        # Start run
        manifest.start_run()
        logger.info(f"Starting workflow: {self.workflow_name}")
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Run directory: {run_dir}")

        all_success = True

        try:
            for step in self.steps:
                success = self._execute_step(step, context)
                if not success:
                    all_success = False
                    # Check if we should continue on failure
                    if not self.config.get("continue_on_failure", False):
                        logger.error(f"Stopping workflow due to step failure: {step.name}")
                        break

            manifest.complete_run(success=all_success)
            manifest.save_summary()

        except Exception as e:
            logger.error(f"Workflow failed with exception: {e}", exc_info=True)
            manifest.complete_run(success=False)
            manifest.save_summary()
            all_success = False

        finally:
            close_workflow_logging(run_id)

        return manifest, all_success

    def _execute_step(self, step: WorkflowStep, context: WorkflowContext) -> bool:
        """Execute a single step with retry logic."""
        logger = context.logger
        manifest = context.manifest

        # Check if already completed (idempotency)
        existing = manifest.get_step(step.name)
        if existing and existing.status == StepStatus.SUCCEEDED:
            logger.info(f"Step already completed: {step.name}")
            return True

        # Check for idempotent completion
        if step.is_idempotent_complete(context):
            logger.info(f"Step outputs already exist (idempotent): {step.name}")
            manifest.skip_step(step.name, reason="outputs_already_exist")
            return True

        # Validate preconditions
        valid, error = step.validate_preconditions(context)
        if not valid:
            logger.error(f"Precondition failed for {step.name}: {error}")
            manifest.add_step(step.name)
            manifest.fail_step(step.name, error=f"Precondition failed: {error}")
            return False

        # Execute with retries
        retry_config = step.retry_config
        max_attempts = retry_config.max_retries + 1
        last_error = None
        result = None

        for attempt in range(max_attempts):
            if attempt > 0:
                delay = retry_config.get_delay(attempt)
                logger.info(f"Retrying {step.name} in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})")
                time.sleep(delay)

            try:
                # Start step
                manifest.start_step(step.name, inputs=context.inputs)
                logger.step_start(step.name, inputs=context.inputs)

                start_time = time.time()

                # Execute
                result = step.execute(context)

                duration = time.time() - start_time

                if result.success:
                    # Validate postconditions
                    valid, error = step.validate_postconditions(context, result)
                    if valid:
                        manifest.complete_step(
                            step.name,
                            outputs=result.outputs,
                            validation_results=result.validation_results,
                            output_files=result.output_files,
                        )
                        logger.step_complete(step.name, duration, outputs=result.outputs)

                        # Store outputs in context
                        for key, value in result.outputs.items():
                            context.set_output(f"{step.name}.{key}", value)

                        return True
                    else:
                        last_error = f"Postcondition failed: {error}"
                        logger.warning(f"Postcondition failed for {step.name}: {error}")
                else:
                    last_error = result.error or "Step returned failure"
                    logger.warning(f"Step {step.name} failed: {last_error}")

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Step {step.name} raised exception: {e}")

                if attempt == max_attempts - 1:
                    # Last attempt - record full traceback
                    tb = traceback.format_exc()
                    manifest.fail_step(step.name, error=last_error, error_traceback=tb)
                    logger.step_failed(step.name, last_error, time.time() - start_time)
                    return False

        # All retries exhausted
        manifest.fail_step(step.name, error=last_error or "All retries exhausted")
        logger.step_failed(step.name, last_error or "All retries exhausted")
        return False

    @staticmethod
    def run_repeated(
        workflow_name: str,
        steps: List[WorkflowStep],
        n_runs: int,
        run_dir_base: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run the workflow N times and aggregate results.

        Returns metrics including:
        - success_rate
        - per_step_success_rates
        - average_durations
        - failure_reasons
        """
        orchestrator = WorkflowOrchestrator(
            workflow_name=workflow_name,
            steps=steps,
            run_dir_base=run_dir_base,
            config=config,
        )

        results = []
        successes = 0
        step_successes: Dict[str, int] = {}
        step_durations: Dict[str, List[float]] = {}
        failure_reasons: List[Dict[str, Any]] = []

        for i in range(n_runs):
            manifest, success = orchestrator.run(inputs=inputs)
            results.append(manifest)

            if success:
                successes += 1
            else:
                # Collect failure info
                for step_name, step in manifest.steps.items():
                    if step.status == StepStatus.FAILED:
                        failure_reasons.append({
                            "run_id": manifest.run_id,
                            "step": step_name,
                            "error": step.error,
                        })

            # Collect per-step metrics
            for step_name, step in manifest.steps.items():
                if step_name not in step_successes:
                    step_successes[step_name] = 0
                    step_durations[step_name] = []

                if step.status == StepStatus.SUCCEEDED:
                    step_successes[step_name] += 1
                    if step.duration_seconds:
                        step_durations[step_name].append(step.duration_seconds)

        # Calculate metrics
        success_rate = successes / n_runs if n_runs > 0 else 0
        per_step_success_rates = {
            name: count / n_runs for name, count in step_successes.items()
        }
        average_durations = {
            name: sum(durations) / len(durations) if durations else 0
            for name, durations in step_durations.items()
        }

        return {
            "n_runs": n_runs,
            "successes": successes,
            "success_rate": success_rate,
            "per_step_success_rates": per_step_success_rates,
            "average_durations": average_durations,
            "failure_reasons": failure_reasons,
            "run_ids": [m.run_id for m in results],
        }
