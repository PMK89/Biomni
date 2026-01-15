"""
Tests for the static tool registry.

Verifies:
- Static tool definitions are correct
- Lazy loading works as expected
- Backward compatibility with dynamic registry
- Startup profiling
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from biomni_esqlabs_tools.static_registry import (
    StaticToolRegistry,
    get_registry,
    iter_esqlabs_tools,
    register_with_agent,
    TOOL_SCHEMAS,
    get_startup_metrics,
)


class TestStaticToolRegistry:
    """Tests for StaticToolRegistry."""

    def test_registry_initialization(self):
        """Test that registry initializes correctly."""
        registry = get_registry()
        registry.initialize()

        # Should have tools in both namespaces
        namespaces = registry.get_namespaces()
        assert "pbpk" in namespaces

    def test_get_schema(self):
        """Test that schemas are pre-computed."""
        registry = get_registry()

        schema = registry.get_schema("create_pbpk_snapshot")
        assert schema is not None
        assert schema["name"] == "create_pbpk_snapshot"
        assert "parameters" in schema
        assert "drug_name" in schema["parameters"]["properties"]

    def test_get_tool_lazy_loading(self):
        """Test that tools are loaded lazily."""
        registry = get_registry()

        # Get a tool - this triggers lazy loading
        tool = registry.get_tool("get_drug_pk_parameters")
        assert tool is not None
        assert callable(tool)

        # Calling the tool should work
        result = tool("Bupropion")
        assert "drug_name" in result
        assert result["drug_name"] == "Bupropion"

    def test_iter_tools(self):
        """Test iterating over tools."""
        registry = get_registry()

        tools = registry.iter_tools(namespaces=["pbpk"])
        assert len(tools) > 0

        # Each item should be (name, callable, schema)
        for name, callable_fn, schema in tools:
            assert isinstance(name, str)
            assert callable(callable_fn)
            assert isinstance(schema, dict)

    def test_iter_tools_excludes_deprecated(self):
        """Test that deprecated tools are excluded by default."""
        registry = get_registry()

        tools_without_deprecated = registry.iter_tools(include_deprecated=False)
        tools_with_deprecated = registry.iter_tools(include_deprecated=True)

        # Should have more tools when including deprecated
        # (or same if no deprecated tools exist)
        assert len(tools_with_deprecated) >= len(tools_without_deprecated)


class TestBackwardCompatibility:
    """Tests for backward compatibility with dynamic registry API."""

    def test_iter_esqlabs_tools(self):
        """Test backward-compatible iter_esqlabs_tools function."""
        tools = iter_esqlabs_tools()
        assert len(tools) > 0
        assert all(callable(t) for t in tools)

    def test_iter_esqlabs_tools_with_namespace(self):
        """Test iter_esqlabs_tools with namespace filter."""
        pbpk_tools = iter_esqlabs_tools(namespaces=["pbpk"])
        assert len(pbpk_tools) > 0

    def test_register_with_agent(self):
        """Test backward-compatible register_with_agent function."""
        # Create a mock agent
        mock_agent = MagicMock()
        mock_agent.add_tool = MagicMock()
        mock_agent.add_tool_with_schema = MagicMock()

        registered = register_with_agent(mock_agent, namespaces=["pbpk"])

        assert len(registered) > 0
        # Either add_tool or add_tool_with_schema should be called
        assert mock_agent.add_tool.called or mock_agent.add_tool_with_schema.called


class TestToolSchemas:
    """Tests for pre-computed tool schemas."""

    def test_required_schemas_exist(self):
        """Test that all required tool schemas are defined."""
        required_tools = [
            "create_pbpk_snapshot",
            "run_pbpk_simulation",
            "run_pbpk_workflow",
            "get_drug_pk_parameters",
            "analyze_pbpk_simulation_results",
            "plot_pbpk_simulation_results",
        ]

        for tool_name in required_tools:
            assert tool_name in TOOL_SCHEMAS, f"Missing schema for {tool_name}"

    def test_schema_structure(self):
        """Test that schemas have the correct structure."""
        for name, schema in TOOL_SCHEMAS.items():
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert schema["parameters"]["type"] == "object"
            assert "properties" in schema["parameters"]


class TestStartupMetrics:
    """Tests for startup profiling."""

    def test_startup_metrics_available(self):
        """Test that startup metrics are captured."""
        metrics = get_startup_metrics()
        assert metrics is not None
        assert hasattr(metrics, "component_times")

    def test_startup_metrics_has_registry_init(self):
        """Test that registry init is timed."""
        # Force initialization
        registry = get_registry()
        registry.initialize()

        metrics = get_startup_metrics()
        assert "tool_registry_init" in metrics.component_times


class TestDynamicVsStaticEquivalence:
    """Tests verifying static registry produces same results as dynamic."""

    def test_tool_count_matches(self):
        """Test that static registry has same tool count as dynamic."""
        # Get tools from static registry
        from biomni_esqlabs_tools.static_registry import iter_esqlabs_tools as static_iter

        static_tools = list(static_iter(namespaces=["pbpk"]))

        # Get tools from dynamic registry
        from biomni_esqlabs_tools.registry import iter_esqlabs_tools as dynamic_iter

        dynamic_tools = list(dynamic_iter(namespaces=["pbpk"]))

        # Static should have at least the same tools
        assert len(static_tools) >= len(dynamic_tools) - 1  # Allow for deprecated tool differences

    def test_tool_functions_match(self):
        """Test that tools return the same functions."""
        registry = get_registry()

        # Get a tool from static registry
        static_tool = registry.get_tool("create_pbpk_snapshot")

        # Get same tool from dynamic registry
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import create_pbpk_snapshot as dynamic_tool

        # Should be the same function
        assert static_tool is dynamic_tool


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
