from __future__ import annotations
from typing import Optional, Dict, Any
import os, json
from biomni.agent import A1

def run_biomni_snapshot(
    drug: str,
    manual_path: str = "snapshot_manual.md",
    data_path: str = "./data",
    llm: str = "gpt-4o-mini",
    locale: str = "en",
    dry_run: bool = False,
    out_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Researches PK/ADME baseline data for a drug using the Biomni agent
    and maps the results to the snapshot schema (from `manual_path`).

    Args:
        drug: Drug name, e.g. "Ibuprofen". (Required)
        manual_path: Path to the snapshot manual/schema markdown file.
        data_path: Data path for Biomni (data lake is downloaded on first run).
        llm: Model ID for the agent (e.g. "gpt-4o-mini").
        locale: "en" or "de" – determines the prompt language.
        dry_run: If True, only validates inputs, no agent call is executed.
        out_path: Optional path to store the result (.json or .md).

    Returns:
        Dict with keys:
        - ok: bool – success
        - drug, llm, data_path, out_path: echo of the input arguments
        - result: Dict[str, Any] – agent output (text under "text" or dict)

    Raises:
        FileNotFoundError: If `manual_path` does not exist.
        ValueError: If `drug` is empty.
        RuntimeError: If the agent call fails.

    Example:
        >>> run_biomni_snapshot("Ibuprofen", manual_path="snapshot_manual.md")
    """
    if not drug or not isinstance(drug, str):
        raise ValueError("Parameter 'drug' must be a non-empty string.")
    if not os.path.exists(manual_path):
        raise FileNotFoundError(f"Manual not found: {manual_path}")

    with open(manual_path, "r", encoding="utf-8") as f:
        manual_text = f.read()

    task = (
        f"Research the relevant PK/ADME baseline data for {drug} on the web, "
        f"map them to the snapshot schema, and create a snapshot configuration file with this schema:\n{manual_text}"
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "message": "Validation successful. No agent call executed.",
            "drug": drug,
            "llm": llm,
            "data_path": data_path,
            "out_path": out_path,
        }

    try:
        agent = A1(path=data_path, llm=llm)
        res = agent.go(task)
    except Exception as e:
        raise RuntimeError(f"Biomni agent call failed: {e}") from e

    payload: Dict[str, Any]
    if isinstance(res, dict):
        payload = res
    else:
        payload = {"text": str(res)}

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        _, ext = os.path.splitext(out_path)
        if ext.lower() in {".md", ".markdown"} and "text" in payload:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(payload["text"])
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "drug": drug,
        "llm": llm,
        "data_path": data_path,
        "out_path": out_path,
        "result": payload,
    }
