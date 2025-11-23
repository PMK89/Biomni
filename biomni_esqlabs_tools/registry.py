"""Registration helpers for ESQlabs toolsets."""
from __future__ import annotations

from typing import Callable, Dict, Iterable, Iterator, List, Sequence

ToolCallable = Callable[..., object]


def _snapshot_tools() -> list[ToolCallable]:
    from .snapshots.create_drug_snapshot import create_drug_snapshot
    from .snapshots.json_rag_builder import (
        rag_json_sections,
        rag_json_template,
        rag_json_answer,
        rag_json_build,
        rag_snapshot_autobuild,
    )
    from .snapshots.biomni_snapshot_tool import run_biomni_snapshot

    return [
        create_drug_snapshot,
        rag_json_sections,
        rag_json_template,
        rag_json_answer,
        rag_json_build,
        rag_snapshot_autobuild,
        run_biomni_snapshot,
    ]


def _pbpk_tools() -> list[ToolCallable]:
    from .pbpk.pksim_runner import run_pksim_snapshot

    return [run_pksim_snapshot]


_TOOLSETS: dict[str, Callable[[], list[ToolCallable]]] = {
    "snapshots": _snapshot_tools,
    "pbpk": _pbpk_tools,
}


def iter_esqlabs_tools(namespaces: Sequence[str] | None = None) -> Iterator[ToolCallable]:
    """Yield ESQlabs tool callables for the selected namespaces."""

    selected = namespaces or list(_TOOLSETS)
    for namespace in selected:
        factory = _TOOLSETS.get(namespace)
        if not factory:
            continue
        for tool in factory():
            yield tool


def register_with_agent(agent: "A1", namespaces: Sequence[str] | None = None) -> list[str]:
    """Register ESQlabs tools on the provided Biomni agent instance.

    Parameters
    ----------
    agent:
        Instance of ``biomni.agent.a1.A1``.
    namespaces:
        Optional iterable restricting the toolsets to load. Supported values
        currently include ``"snapshots"`` and ``"pbpk"``.
    Returns
    -------
    list[str]
        List of tool names that were registered.
    """

    registered: list[str] = []
    for tool in iter_esqlabs_tools(namespaces):
        agent.add_tool(tool)
        registered.append(tool.__name__)
    return registered


__all__ = ["iter_esqlabs_tools", "register_with_agent"]
