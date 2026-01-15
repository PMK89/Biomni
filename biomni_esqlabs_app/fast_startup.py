"""
Fast startup module for Biomni ESQlabs application.

Provides optimized initialization that:
- Uses static tool registry (no per-tool LLM calls)
- Defers heavy imports
- Provides startup profiling
- Enables optional background KB sync

Usage:
    from biomni_esqlabs_app.fast_startup import initialize_agent, get_startup_summary

    agent = initialize_agent()
    print(get_startup_summary())
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from biomni.agent.a1 import A1

logger = logging.getLogger(__name__)


@dataclass
class StartupProfile:
    """Profile of startup timing."""
    start_time: float = field(default_factory=time.time)
    phases: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    tools_registered: int = 0
    total_time: float = 0.0

    def start_phase(self, name: str) -> float:
        return time.time()

    def end_phase(self, name: str, start: float) -> None:
        self.phases[name] = time.time() - start

    def finalize(self) -> None:
        self.total_time = time.time() - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_time_seconds": self.total_time,
            "phases": self.phases,
            "tools_registered": self.tools_registered,
            "warnings": self.warnings,
            "errors": self.errors,
        }


_startup_profile: Optional[StartupProfile] = None


def get_startup_summary() -> Dict[str, Any]:
    """Get a summary of startup timing and status."""
    if _startup_profile is None:
        return {"status": "not_initialized"}
    return _startup_profile.to_dict()


def initialize_agent(
    data_path: Optional[Path] = None,
    enable_kb_sync: Optional[bool] = None,
    use_static_registry: bool = True,
) -> Optional["A1"]:
    """
    Initialize the Biomni agent with optimized startup.

    Args:
        data_path: Path to Biomni data directory
        enable_kb_sync: Enable background KB sync (default: check ENABLE_KB_SYNC env var)
        use_static_registry: Use static tool registry for fast startup

    Returns:
        Initialized agent or None if initialization failed
    """
    global _startup_profile
    _startup_profile = StartupProfile()
    profile = _startup_profile

    logger.info("=" * 60)
    logger.info("Starting Biomni Agent Initialization (Fast Startup)")
    logger.info("=" * 60)

    # Phase 1: Environment and configuration
    start = profile.start_phase("config")
    try:
        from .config import settings
        from .data_paths import BIOMNI_DATA_PATH

        if data_path is None:
            data_path = BIOMNI_DATA_PATH

        if not settings.OPENAI_API_KEY:
            profile.errors.append("OPENAI_API_KEY not set")
            logger.error("OpenAI API key not found. Agent not initialized.")
            profile.end_phase("config", start)
            profile.finalize()
            return None

        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        profile.end_phase("config", start)
        logger.info(f"  Config loaded in {profile.phases['config']:.3f}s")
    except Exception as e:
        profile.errors.append(f"Config error: {e}")
        logger.error(f"Failed to load configuration: {e}")
        profile.finalize()
        return None

    # Phase 2: Create agent
    start = profile.start_phase("agent_create")
    try:
        from biomni.agent.a1 import A1
        from biomni.config import default_config

        agent = A1(path=str(data_path))
        profile.end_phase("agent_create", start)
        logger.info(f"  Agent created in {profile.phases['agent_create']:.3f}s")
    except Exception as e:
        profile.errors.append(f"Agent creation error: {e}")
        logger.error(f"Failed to create agent: {e}")
        profile.finalize()
        return None

    # Phase 3: Register ALL tools via static registry (literature + ESQlabs)
    # This is the fast path - uses pre-computed schemas, no LLM calls
    start = profile.start_phase("tool_registration")
    if use_static_registry:
        try:
            from biomni_esqlabs_tools.static_registry import get_registry

            registry = get_registry()

            # Register all tools from all namespaces using static schemas
            # This includes: literature, pbpk, snapshots
            for name, callable_fn, schema in registry.iter_tools():
                try:
                    # Use pre-computed schema if agent supports it
                    if hasattr(agent, 'add_tool_with_schema'):
                        agent.add_tool_with_schema(callable_fn, schema)
                    else:
                        # Fallback - still faster than dynamic since we're batching
                        agent.add_tool(callable_fn)
                    profile.tools_registered += 1
                except Exception as e:
                    profile.warnings.append(f"Failed to register {name}: {e}")
                    logger.warning(f"Failed to register tool {name}: {e}")

            logger.info(f"  Registered {profile.tools_registered} tools via static registry")
        except ImportError as e:
            logger.warning(f"Static registry not available, falling back to dynamic loading: {e}")
            _register_all_tools_dynamic(agent, profile)
        except Exception as e:
            profile.warnings.append(f"Static registry error: {e}")
            logger.warning(f"Static registry failed, falling back: {e}")
            _register_all_tools_dynamic(agent, profile)
    else:
        _register_all_tools_dynamic(agent, profile)

    profile.end_phase("tool_registration", start)
    logger.info(f"  All tools registered in {profile.phases['tool_registration']:.3f}s")

    # Phase 5: Optional KB sync
    if enable_kb_sync is None:
        enable_kb_sync = os.environ.get("ENABLE_KB_SYNC", "").lower() in ("1", "true", "yes")

    if enable_kb_sync:
        start = profile.start_phase("kb_sync_start")
        try:
            from biomni_esqlabs_tools.static_registry import start_background_kb_sync
            start_background_kb_sync(str(data_path))
            profile.end_phase("kb_sync_start", start)
            logger.info(f"  KB sync scheduled in {profile.phases['kb_sync_start']:.3f}s")
        except Exception as e:
            profile.warnings.append(f"KB sync error: {e}")
            logger.warning(f"Failed to start KB sync: {e}")
            profile.end_phase("kb_sync_start", start)

    # Finalize
    profile.finalize()

    logger.info("=" * 60)
    logger.info("STARTUP COMPLETE")
    logger.info("=" * 60)
    for phase, duration in sorted(profile.phases.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"  {phase}: {duration:.3f}s")
    logger.info("-" * 60)
    logger.info(f"  Total: {profile.total_time:.3f}s")
    logger.info(f"  Tools: {profile.tools_registered}")
    if profile.warnings:
        logger.info(f"  Warnings: {len(profile.warnings)}")
    if profile.errors:
        logger.error(f"  Errors: {len(profile.errors)}")
    logger.info("=" * 60)

    return agent


def _register_all_tools_dynamic(agent: "A1", profile: StartupProfile) -> None:
    """Fallback dynamic tool registration for all tools (literature + ESQlabs)."""
    # Register literature tools
    try:
        from biomni.tool.literature import (
            query_pubmed,
            query_scholar,
            query_arxiv,
            search_google,
            advanced_web_search,
            download_open_access_paper_pdf,
            download_pubmed_open_access_pdfs,
        )

        literature_tools = [
            query_pubmed,
            query_scholar,
            query_arxiv,
            search_google,
            advanced_web_search,
            download_open_access_paper_pdf,
            download_pubmed_open_access_pdfs,
        ]

        for tool in literature_tools:
            try:
                agent.add_tool(tool)
                profile.tools_registered += 1
            except Exception as e:
                profile.warnings.append(f"Failed to register {tool.__name__}: {e}")
                logger.warning(f"Failed to register tool {tool.__name__}: {e}")

    except ImportError as e:
        profile.warnings.append(f"Literature tools import error: {e}")
        logger.warning(f"Failed to import literature tools: {e}")

    # Register ESQlabs PBPK tools
    try:
        from biomni_esqlabs_tools.pbpk.pbpk_workflow import (
            create_pbpk_snapshot,
            run_pbpk_simulation,
            run_pbpk_workflow,
            get_drug_pk_parameters,
            analyze_pbpk_simulation_results,
            plot_pbpk_simulation_results,
        )
        from biomni_esqlabs_tools.pbpk.pksim_runner import run_pksim_snapshot

        esqlabs_tools = [
            create_pbpk_snapshot,
            run_pbpk_simulation,
            run_pbpk_workflow,
            get_drug_pk_parameters,
            analyze_pbpk_simulation_results,
            plot_pbpk_simulation_results,
            run_pksim_snapshot,
        ]

        for tool in esqlabs_tools:
            try:
                agent.add_tool(tool)
                profile.tools_registered += 1
            except Exception as e:
                profile.warnings.append(f"Failed to register {tool.__name__}: {e}")
                logger.warning(f"Failed to register tool {tool.__name__}: {e}")

    except ImportError as e:
        profile.warnings.append(f"ESQlabs tools import error: {e}")
        logger.warning(f"Failed to import ESQlabs tools: {e}")
