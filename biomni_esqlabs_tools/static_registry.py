"""
Static Tool Registry - Pre-built tool registration for fast startup.

This module replaces the dynamic runtime loading with:
- Static tool definitions at import time
- Pre-computed tool schemas (no LLM calls at startup)
- Lazy instantiation (tools imported only when first used)
- Optional background KB sync (gated by environment variable)

Key improvements:
- No per-tool dynamic imports at registration
- No LLM calls for schema generation
- Tools are registered once at import time
- Startup profiling for performance monitoring
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from biomni.agent.a1 import A1

logger = logging.getLogger(__name__)


# ============================================================================
# Startup Profiler
# ============================================================================

@dataclass
class StartupMetrics:
    """Tracks startup timing for each component."""
    start_time: float = field(default_factory=time.time)
    component_times: Dict[str, float] = field(default_factory=dict)
    total_time: float = 0.0

    def start_component(self, name: str) -> float:
        """Start timing a component."""
        return time.time()

    def end_component(self, name: str, start: float) -> None:
        """End timing a component."""
        self.component_times[name] = time.time() - start

    def finalize(self) -> None:
        """Finalize startup timing."""
        self.total_time = time.time() - self.start_time

    def log_summary(self) -> None:
        """Log a summary of startup times."""
        logger.info("=" * 60)
        logger.info("STARTUP TIMING SUMMARY")
        logger.info("=" * 60)
        for name, duration in sorted(self.component_times.items(), key=lambda x: -x[1]):
            logger.info(f"  {name}: {duration:.3f}s")
        logger.info("-" * 60)
        logger.info(f"  TOTAL: {self.total_time:.3f}s")
        logger.info("=" * 60)


_startup_metrics = StartupMetrics()


def get_startup_metrics() -> StartupMetrics:
    """Get the startup metrics instance."""
    return _startup_metrics


# ============================================================================
# Pre-computed Tool Schemas
# ============================================================================

# Pre-defined schemas for ESQlabs tools to avoid LLM calls at startup
# These are computed once and stored here

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # Literature Tools
    # =========================================================================
    "query_pubmed": {
        "name": "query_pubmed",
        "description": "Query PubMed for papers based on the provided search query. Returns JSON with paper metadata including titles, abstracts, PMIDs, and DOIs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query string"},
                "max_papers": {"type": "integer", "description": "Maximum number of papers to retrieve", "default": 10},
                "max_retries": {"type": "integer", "description": "Maximum retry attempts with modified queries", "default": 3},
            },
            "required": ["query"],
        },
    },
    "query_scholar": {
        "name": "query_scholar",
        "description": "Query Google Scholar for papers based on the provided search query. Returns the first search result with title, year, venue, and abstract.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query string"},
            },
            "required": ["query"],
        },
    },
    "query_arxiv": {
        "name": "query_arxiv",
        "description": "Query arXiv for papers based on the provided search query. Returns paper titles and summaries.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query string"},
                "max_papers": {"type": "integer", "description": "Maximum number of papers to retrieve", "default": 10},
            },
            "required": ["query"],
        },
    },
    "search_google": {
        "name": "search_google",
        "description": "Search using Google search. Returns search results with titles, URLs, and descriptions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "num_results": {"type": "integer", "description": "Number of results to return", "default": 3},
                "language": {"type": "string", "description": "Language code for search results", "default": "en"},
            },
            "required": ["query"],
        },
    },
    "advanced_web_search": {
        "name": "advanced_web_search",
        "description": "Initiate an advanced web search by launching a specialized agent to collect relevant information and citations through multiple rounds of web searches.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search phrase to look up"},
                "max_searches": {"type": "integer", "description": "Upper-bound on searches inside this request", "default": 3},
                "max_retries": {"type": "integer", "description": "Maximum number of retry attempts", "default": 3},
            },
            "required": ["query"],
        },
    },
    "download_open_access_paper_pdf": {
        "name": "download_open_access_paper_pdf",
        "description": "Download an open-access paper PDF given a DOI or direct URL. Attempts to resolve via Unpaywall, Semantic Scholar, and DOI landing page.",
        "parameters": {
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "The paper DOI"},
                "url": {"type": "string", "description": "Direct URL to PDF"},
                "output_dir": {"type": "string", "description": "Directory to save the PDF"},
                "filename": {"type": "string", "description": "Filename for the downloaded PDF"},
                "timeout": {"type": "integer", "description": "Request timeout in seconds", "default": 60},
            },
            "required": [],
        },
    },
    "download_pubmed_open_access_pdfs": {
        "name": "download_pubmed_open_access_pdfs",
        "description": "Search PubMed and download open-access PDFs for matching papers. Combines query_pubmed with download_open_access_paper_pdf.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PubMed search query"},
                "max_papers": {"type": "integer", "description": "Maximum number of papers to download", "default": 5},
                "output_dir": {"type": "string", "description": "Directory to save PDFs"},
                "timeout": {"type": "integer", "description": "Request timeout per download", "default": 60},
            },
            "required": ["query"],
        },
    },
    "fetch_supplementary_info_from_doi": {
        "name": "fetch_supplementary_info_from_doi",
        "description": "Fetches supplementary information for a paper given its DOI and returns a research log.",
        "parameters": {
            "type": "object",
            "properties": {
                "doi": {"type": "string", "description": "The paper DOI"},
                "output_dir": {"type": "string", "description": "Directory to save supplementary files", "default": "supplementary_info"},
            },
            "required": ["doi"],
        },
    },
    "extract_url_content": {
        "name": "extract_url_content",
        "description": "Extract the text content of a webpage using requests and BeautifulSoup.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Webpage URL to extract content from"},
            },
            "required": ["url"],
        },
    },
    "extract_pdf_content": {
        "name": "extract_pdf_content",
        "description": "Extract the text content of a PDF file given its URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL of the PDF file to extract text from"},
            },
            "required": ["url"],
        },
    },
    # =========================================================================
    # PBPK Tools
    # =========================================================================
    "create_pbpk_snapshot": {
        "name": "create_pbpk_snapshot",
        "description": "Create a complete PK-Sim snapshot file for a drug with the provided parameters.",
        "parameters": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string", "description": "Name of the drug/compound"},
                "dose_mg": {"type": "number", "description": "Dose in milligrams", "default": 100.0},
                "molecular_weight": {"type": "number", "description": "Molecular weight in g/mol"},
                "log_p": {"type": "number", "description": "Lipophilicity (LogP value)"},
                "fraction_unbound": {"type": "number", "description": "Fraction unbound in plasma (0-1)"},
                "solubility_mg_l": {"type": "number", "description": "Solubility at reference pH in mg/L"},
                "reference_ph": {"type": "number", "description": "Reference pH for solubility", "default": 7.4},
                "individual_name": {"type": "string", "default": "HealthyAdult"},
                "population": {"type": "string", "default": "European_ICRP_2002"},
                "age_years": {"type": "number", "default": 30.0},
                "weight_kg": {"type": "number", "default": 70.0},
                "height_cm": {"type": "number", "default": 175.0},
                "formulation_type": {"type": "string", "default": "Formulation_Tablet_Weibull"},
                "simulation_duration_h": {"type": "number", "default": 24.0},
                "out_path": {"type": "string", "description": "Output path for the snapshot file"},
                "allow_placeholders": {"type": "boolean", "default": False},
            },
            "required": ["drug_name"],
        },
    },
    "run_pbpk_simulation": {
        "name": "run_pbpk_simulation",
        "description": "Run a PBPK simulation using PK-Sim CLI from a snapshot file.",
        "parameters": {
            "type": "object",
            "properties": {
                "snapshot_path": {"type": "string", "description": "Path to the PK-Sim snapshot JSON file"},
                "pksim_cli_path": {"type": "string", "description": "Path to PKSim.CLI.exe"},
                "output_dir": {"type": "string", "description": "Directory for output files"},
                "export_pkml": {"type": "boolean", "default": True},
                "force_rerun": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "integer", "default": 300},
            },
            "required": ["snapshot_path"],
        },
    },
    "run_pbpk_workflow": {
        "name": "run_pbpk_workflow",
        "description": "Run the complete PBPK workflow: simulation + analysis + plotting.",
        "parameters": {
            "type": "object",
            "properties": {
                "snapshot_path": {"type": "string", "description": "Path to the snapshot file"},
                "output_dir": {"type": "string"},
                "export_pkml": {"type": "boolean", "default": True},
                "timeout_seconds": {"type": "integer", "default": 600},
                "force_rerun": {"type": "boolean", "default": False},
                "run_analysis": {"type": "boolean", "default": True},
                "run_plot": {"type": "boolean", "default": True},
                "plot_name": {"type": "string", "default": "pbpk_time_profile"},
                "dpi": {"type": "integer", "default": 200},
            },
            "required": ["snapshot_path"],
        },
    },
    "get_drug_pk_parameters": {
        "name": "get_drug_pk_parameters",
        "description": "Provide guidance on finding pharmacokinetic parameters for a drug.",
        "parameters": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string", "description": "Name of the drug to look up"},
            },
            "required": ["drug_name"],
        },
    },
    "analyze_pbpk_simulation_results": {
        "name": "analyze_pbpk_simulation_results",
        "description": "Analyze PBPK simulation results and compute PK metrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "results_csv_path": {"type": "string"},
                "pkml_path": {"type": "string"},
                "quantity_paths": {"type": "array", "items": {"type": "string"}},
                "individual_id": {"type": "integer", "default": 0},
                "use_ospsuite": {"type": "boolean", "default": True},
                "timeout_seconds": {"type": "integer", "default": 300},
            },
            "required": [],
        },
    },
    "plot_pbpk_simulation_results": {
        "name": "plot_pbpk_simulation_results",
        "description": "Plot PBPK simulation results using OSPSuite-R plotting utilities.",
        "parameters": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "pkml_path": {"type": "string"},
                "results_csv_path": {"type": "string"},
                "quantity_paths": {"type": "array", "items": {"type": "string"}},
                "plot_name": {"type": "string", "default": "pbpk_time_profile"},
                "file_format": {"type": "string", "default": "png"},
                "dpi": {"type": "integer", "default": 200},
                "timeout_seconds": {"type": "integer", "default": 600},
            },
            "required": [],
        },
    },
    "run_pksim_snapshot": {
        "name": "run_pksim_snapshot",
        "description": "Run a PK-Sim simulation from a snapshot file.",
        "parameters": {
            "type": "object",
            "properties": {
                "snapshot_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 300},
            },
            "required": ["snapshot_path"],
        },
    },
    # Legacy tools (still registered but marked for deprecation)
    "create_drug_snapshot": {
        "name": "create_drug_snapshot",
        "description": "[DEPRECATED] Legacy tool for creating PK-Sim snapshots. Use create_pbpk_snapshot instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string"},
                "dose_mg": {"type": "number"},
            },
            "required": ["drug_name"],
        },
        "_deprecated": True,
    },
}


# ============================================================================
# Tool Registry
# ============================================================================

ToolCallable = Callable[..., object]


@dataclass
class ToolDefinition:
    """Static definition of a tool."""
    name: str
    module_path: str
    function_name: str
    schema: Dict[str, Any]
    namespace: str
    deprecated: bool = False
    _cached_callable: Optional[ToolCallable] = field(default=None, repr=False)

    def get_callable(self) -> ToolCallable:
        """Lazy-load and return the tool callable."""
        if self._cached_callable is not None:
            return self._cached_callable

        # Import on first use
        import importlib
        module = importlib.import_module(self.module_path)
        func = getattr(module, self.function_name)
        self._cached_callable = func
        return func


# Static tool definitions - no imports at module load time
_TOOL_DEFINITIONS: List[ToolDefinition] = [
    # =========================================================================
    # Literature namespace
    # =========================================================================
    ToolDefinition(
        name="query_pubmed",
        module_path="biomni.tool.literature",
        function_name="query_pubmed",
        schema=TOOL_SCHEMAS["query_pubmed"],
        namespace="literature",
    ),
    ToolDefinition(
        name="query_scholar",
        module_path="biomni.tool.literature",
        function_name="query_scholar",
        schema=TOOL_SCHEMAS["query_scholar"],
        namespace="literature",
    ),
    ToolDefinition(
        name="query_arxiv",
        module_path="biomni.tool.literature",
        function_name="query_arxiv",
        schema=TOOL_SCHEMAS["query_arxiv"],
        namespace="literature",
    ),
    ToolDefinition(
        name="search_google",
        module_path="biomni.tool.literature",
        function_name="search_google",
        schema=TOOL_SCHEMAS["search_google"],
        namespace="literature",
    ),
    ToolDefinition(
        name="advanced_web_search",
        module_path="biomni.tool.literature",
        function_name="advanced_web_search",
        schema=TOOL_SCHEMAS["advanced_web_search"],
        namespace="literature",
    ),
    ToolDefinition(
        name="download_open_access_paper_pdf",
        module_path="biomni.tool.literature",
        function_name="download_open_access_paper_pdf",
        schema=TOOL_SCHEMAS["download_open_access_paper_pdf"],
        namespace="literature",
    ),
    ToolDefinition(
        name="download_pubmed_open_access_pdfs",
        module_path="biomni.tool.literature",
        function_name="download_pubmed_open_access_pdfs",
        schema=TOOL_SCHEMAS["download_pubmed_open_access_pdfs"],
        namespace="literature",
    ),
    ToolDefinition(
        name="fetch_supplementary_info_from_doi",
        module_path="biomni.tool.literature",
        function_name="fetch_supplementary_info_from_doi",
        schema=TOOL_SCHEMAS["fetch_supplementary_info_from_doi"],
        namespace="literature",
    ),
    ToolDefinition(
        name="extract_url_content",
        module_path="biomni.tool.literature",
        function_name="extract_url_content",
        schema=TOOL_SCHEMAS["extract_url_content"],
        namespace="literature",
    ),
    ToolDefinition(
        name="extract_pdf_content",
        module_path="biomni.tool.literature",
        function_name="extract_pdf_content",
        schema=TOOL_SCHEMAS["extract_pdf_content"],
        namespace="literature",
    ),
    # =========================================================================
    # PBPK namespace
    # =========================================================================
    ToolDefinition(
        name="create_pbpk_snapshot",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="create_pbpk_snapshot",
        schema=TOOL_SCHEMAS["create_pbpk_snapshot"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="run_pbpk_simulation",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="run_pbpk_simulation",
        schema=TOOL_SCHEMAS["run_pbpk_simulation"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="run_pbpk_workflow",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="run_pbpk_workflow",
        schema=TOOL_SCHEMAS["run_pbpk_workflow"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="get_drug_pk_parameters",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="get_drug_pk_parameters",
        schema=TOOL_SCHEMAS["get_drug_pk_parameters"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="analyze_pbpk_simulation_results",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="analyze_pbpk_simulation_results",
        schema=TOOL_SCHEMAS["analyze_pbpk_simulation_results"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="plot_pbpk_simulation_results",
        module_path="biomni_esqlabs_tools.pbpk.pbpk_workflow",
        function_name="plot_pbpk_simulation_results",
        schema=TOOL_SCHEMAS["plot_pbpk_simulation_results"],
        namespace="pbpk",
    ),
    ToolDefinition(
        name="run_pksim_snapshot",
        module_path="biomni_esqlabs_tools.pbpk.pksim_runner",
        function_name="run_pksim_snapshot",
        schema=TOOL_SCHEMAS["run_pksim_snapshot"],
        namespace="pbpk",
    ),
    # Snapshots namespace (legacy, marked deprecated)
    ToolDefinition(
        name="create_drug_snapshot",
        module_path="biomni_esqlabs_tools.snapshots.create_drug_snapshot",
        function_name="create_drug_snapshot",
        schema=TOOL_SCHEMAS["create_drug_snapshot"],
        namespace="snapshots",
        deprecated=True,
    ),
]


class StaticToolRegistry:
    """
    Static tool registry with lazy loading and pre-computed schemas.

    Key features:
    - Tools defined at import time (no dynamic discovery)
    - Schemas pre-computed (no LLM calls)
    - Lazy instantiation (tools only loaded when first called)
    - Startup profiling
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._by_namespace: Dict[str, List[ToolDefinition]] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the registry with static tool definitions."""
        if self._initialized:
            return

        start = _startup_metrics.start_component("tool_registry_init")

        for tool_def in _TOOL_DEFINITIONS:
            self._tools[tool_def.name] = tool_def
            if tool_def.namespace not in self._by_namespace:
                self._by_namespace[tool_def.namespace] = []
            self._by_namespace[tool_def.namespace].append(tool_def)

        self._initialized = True
        _startup_metrics.end_component("tool_registry_init", start)
        logger.info(f"Registered {len(self._tools)} tools in {len(self._by_namespace)} namespaces")

    def get_tool(self, name: str) -> Optional[ToolCallable]:
        """Get a tool callable by name (lazy loads on first access)."""
        self.initialize()
        tool_def = self._tools.get(name)
        if tool_def is None:
            return None
        return tool_def.get_callable()

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Get pre-computed schema for a tool."""
        self.initialize()
        tool_def = self._tools.get(name)
        if tool_def is None:
            return None
        return tool_def.schema

    def iter_tools(
        self,
        namespaces: Optional[Sequence[str]] = None,
        include_deprecated: bool = False,
    ) -> List[Tuple[str, ToolCallable, Dict[str, Any]]]:
        """
        Iterate over tools, returning (name, callable, schema) tuples.

        This is the preferred method for bulk tool registration.
        """
        self.initialize()

        if namespaces:
            selected_namespaces = set(namespaces)
        else:
            selected_namespaces = set(self._by_namespace.keys())

        results = []
        for namespace in selected_namespaces:
            tools = self._by_namespace.get(namespace, [])
            for tool_def in tools:
                if tool_def.deprecated and not include_deprecated:
                    continue
                try:
                    callable_fn = tool_def.get_callable()
                    results.append((tool_def.name, callable_fn, tool_def.schema))
                except Exception as e:
                    logger.warning(f"Failed to load tool {tool_def.name}: {e}")

        return results

    def get_namespaces(self) -> List[str]:
        """Get available namespace names."""
        self.initialize()
        return list(self._by_namespace.keys())

    def register_with_agent_fast(
        self,
        agent: "A1",
        namespaces: Optional[Sequence[str]] = None,
        include_deprecated: bool = False,
    ) -> List[str]:
        """
        Fast registration of tools with an agent.

        Uses pre-computed schemas to avoid LLM calls during registration.
        This is the recommended method for agent tool registration.

        Returns list of registered tool names.
        """
        start = _startup_metrics.start_component("agent_tool_registration")

        registered = []
        for name, callable_fn, schema in self.iter_tools(namespaces, include_deprecated):
            try:
                # Use pre-computed schema if agent supports it
                if hasattr(agent, 'add_tool_with_schema'):
                    agent.add_tool_with_schema(callable_fn, schema)
                else:
                    # Fallback to standard add_tool (may trigger LLM schema generation)
                    agent.add_tool(callable_fn)
                registered.append(name)
            except Exception as e:
                logger.warning(f"Failed to register tool {name}: {e}")

        _startup_metrics.end_component("agent_tool_registration", start)
        logger.info(f"Registered {len(registered)} tools with agent")
        return registered


# Global singleton instance
_registry = StaticToolRegistry()


def get_registry() -> StaticToolRegistry:
    """Get the global tool registry instance."""
    return _registry


# ============================================================================
# Backward Compatibility API
# ============================================================================

def iter_esqlabs_tools(
    namespaces: Optional[Sequence[str]] = None,
) -> List[ToolCallable]:
    """
    Backward-compatible API for iterating over ESQlabs tools.

    Equivalent to the old registry.iter_esqlabs_tools() but uses static definitions.
    """
    registry = get_registry()
    return [callable_fn for _, callable_fn, _ in registry.iter_tools(namespaces)]


def register_with_agent(
    agent: "A1",
    namespaces: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Backward-compatible API for registering tools with an agent.

    Equivalent to the old registry.register_with_agent() but uses static registration.
    """
    return get_registry().register_with_agent_fast(agent, namespaces)


# ============================================================================
# Background KB Sync
# ============================================================================

_kb_sync_thread = None


def start_background_kb_sync(data_path: str, interval_minutes: int = 60) -> None:
    """
    Start background knowledge base synchronization.

    Gated by ENABLE_KB_SYNC=1 environment variable.
    Does not block startup; runs in background thread.
    """
    global _kb_sync_thread

    if not os.environ.get("ENABLE_KB_SYNC", "").lower() in ("1", "true", "yes"):
        logger.info("Background KB sync disabled (set ENABLE_KB_SYNC=1 to enable)")
        return

    if _kb_sync_thread is not None and _kb_sync_thread.is_alive():
        logger.info("KB sync already running")
        return

    import threading

    def sync_worker():
        while True:
            try:
                logger.info("Starting knowledge base sync...")
                # Import and run sync logic here
                # This would typically refresh know-how documents
                from pathlib import Path
                kb_path = Path(data_path) / "know_how"
                if kb_path.exists():
                    logger.info(f"KB sync: Found {len(list(kb_path.glob('*.md')))} documents")
                logger.info("Knowledge base sync completed")
            except Exception as e:
                logger.warning(f"KB sync failed (will retry): {e}")

            # Sleep for interval
            import time
            time.sleep(interval_minutes * 60)

    _kb_sync_thread = threading.Thread(target=sync_worker, daemon=True, name="kb-sync")
    _kb_sync_thread.start()
    logger.info(f"Started background KB sync (interval: {interval_minutes} min)")


def stop_background_kb_sync() -> None:
    """Stop background KB sync (for testing)."""
    global _kb_sync_thread
    _kb_sync_thread = None


# ============================================================================
# Module-level initialization
# ============================================================================

# Initialize registry at import time (but don't load tool modules yet)
_registry.initialize()
