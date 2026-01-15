"""
Pytest configuration and shared fixtures for Biomni tests.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_run_dir():
    """Create a temporary directory for test runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def bupropion_params():
    """Standard Bupropion parameters for testing."""
    return {
        "drug_name": "Bupropion",
        "dose_mg": 150.0,
        "molecular_weight": 239.74,
        "log_p": 3.6,
        "fraction_unbound": 0.16,
        "solubility_mg_l": 312.0,
        "simulation_duration_h": 24.0,
    }


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing tool registration."""
    from unittest.mock import MagicMock

    agent = MagicMock()
    agent.add_tool = MagicMock()
    agent.add_tool_with_schema = MagicMock()
    return agent


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Clean up environment variables for each test."""
    # Remove any test-related env vars that might interfere
    for key in list(os.environ.keys()):
        if key.startswith("BIOMNI_TEST_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def workflow_context(temp_run_dir):
    """Create a workflow context for testing."""
    from biomni_esqlabs_tools.workflow.manifest import RunManifest
    from biomni_esqlabs_tools.workflow.logging_config import setup_workflow_logging
    from biomni_esqlabs_tools.workflow.orchestrator import WorkflowContext

    run_id = "test_run"
    manifest = RunManifest(run_id=run_id, run_dir=temp_run_dir)
    logger = setup_workflow_logging(run_id, temp_run_dir, console_output=False)

    return WorkflowContext(
        run_id=run_id,
        run_dir=temp_run_dir,
        manifest=manifest,
        logger=logger,
    )
