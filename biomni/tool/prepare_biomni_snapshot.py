# custom_tools/biomni_snapshot_prep.py
from __future__ import annotations
import os
from typing import Dict, Any

def prepare_biomni_snapshot(
    drug: str,
    manual_path: str = "snapshot_manual.md",
    locale: str = "en",
) -> Dict[str, Any]:
    """
    Build a complete snapshot task without running an internal LLM/agent.
    Returns a dictionary with a user-ready prompt and message list
    that the calling agent/LLM can process directly.

    Args:
        drug: Name of the compound, e.g. "Ibuprofen". (Required)
        manual_path: Path to the snapshot schema/manual in Markdown.
        locale: "en" or "de" – determines prompt language.

    Returns:
        dict containing:
        - ok: True if preparation succeeded
        - drug: the drug name (echo)
        - prompt: the full user task as string
        - messages: list of {role, content} suitable for chat models
        - hints: optional metadata with expected output and next steps

    Raises:
        FileNotFoundError: if manual_path does not exist.
        ValueError: if drug is empty or not a string.
    """
    if not drug or not isinstance(drug, str):
        raise ValueError("Parameter 'drug' must be a non-empty string.")
    if not os.path.exists(manual_path):
        raise FileNotFoundError(f"Manual not found: {manual_path}")

    with open(manual_path, "r", encoding="utf-8") as f:
        manual_text = f.read()

    
    user_task = (
        f"Research the relevant PK/ADME baseline data for {drug} on the web, "
        f"map them to the snapshot schema, and create a snapshot configuration file with this schema:\n{manual_text}"
        f"For safing use the tool snapshot_builder with its specific arguments."
    )
    system_hint = (
        "You are a meticulous biomedical research assistant. "
        "Cite reliable sources, strictly align outputs with the provided snapshot schema, "
        "and state assumptions explicitly."
    )


    messages = [
        {"role": "system", "content": system_hint},
        {"role": "user", "content": user_task},
    ]

    return {
        "ok": True,
        "drug": drug,
        "prompt": user_task,
        "messages": messages,
        "hints": {
            "expected_output": "Snapshot configuration (JSON/MD) consistent with schema, including citations.",
            "next_steps": [
                "Call the outer agent/LLM with `messages`.",
                "Optionally validate the output against the schema.",
                "Persist the result to snapshots/{drug}.json or .md."
            ],
        },
    }
