import asyncio
import contextlib
import inspect
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import gradio as gr
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

from .config import settings
from biomni.config import default_config
from .data_paths import BIOMNI_DATA_PATH, get_chat_dir, sanitize_segment
from .upload import router as upload_router, save_agent_run_record
from biomni.tool.literature import (
    query_pubmed,
    query_scholar,
    query_arxiv,
    search_google,
    advanced_web_search,
    advanced_web_search_claude,
    download_open_access_paper_pdf,
    download_pubmed_open_access_pdfs
)


def _prompt_requests_pbpk(prompt: str) -> bool:
    if not prompt:
        return False
    lowered = prompt.lower()
    return any(
        token in lowered
        for token in (
            "pbpk",
            "pk-sim",
            "pksim",
            "ospsuite",
            "simulate",
            "simulation",
            "run the simulation",
            "run a simulation",
        )
    )


def _prompt_requests_literature(prompt: str) -> bool:
    if not prompt:
        return False
    lowered = prompt.lower()
    return any(
        token in lowered
        for token in (
            "save all papers",
            "download all papers",
            "save papers",
            "download papers",
            "save all sources",
            "download pdf",
            "download pdfs",
            "downloaded open-access pdf",
            "pubmed",
            "literature",
        )
    )


def _infer_pubmed_query(prompt: str) -> str:
    text = (prompt or "")
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9\-]{2,}\b", text)
    blacklist = {
        "IMPORTANT",
        "Directory",
        "CHAT_DIR",
        "PBPK",
        "PK",
        "Simulate",
        "Simulation",
        "Protocol",
        "Create",
        "Save",
        "Download",
        "PubMed",
        "Google",
        "Scholar",
    }
    drugs: list[str] = []
    for c in candidates:
        if c in blacklist:
            continue
        if c.lower() in {"mg", "bid", "auc", "cmax", "tmax"}:
            continue
        if c not in drugs:
            drugs.append(c)
        if len(drugs) >= 3:
            break
    if drugs:
        joined = " ".join(drugs)
        return f"{joined} pharmacokinetics"
    return "pharmacokinetics"


def _has_pbpk_outputs(chat_dir: Path) -> bool:
    out_dir = chat_dir / "simulation_outputs"
    if not out_dir.exists():
        return False
    has_csv = any(out_dir.rglob("*-Results.csv")) or any(out_dir.rglob("*Results.csv"))
    has_pkml = any(out_dir.rglob("*.pkml"))
    return has_csv or has_pkml


def _has_pbpk_plots(chat_dir: Path) -> bool:
    plots_dir = chat_dir / "simulation_outputs" / "plots"
    if not plots_dir.exists():
        return False
    return any(plots_dir.rglob("*.png")) or any(plots_dir.rglob("*.pdf")) or any(plots_dir.rglob("*.svg"))


def _find_latest_snapshot_file(chat_dir: Path) -> Optional[Path]:
    candidates = sorted(
        (p for p in chat_dir.rglob("*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    preferred = [p for p in candidates if "snapshot" in p.name.lower()]
    ordered = preferred + [p for p in candidates if p not in preferred]

    for path in ordered:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if _looks_like_snapshot(payload):
                return path
        except Exception:
            continue
    return None


def _infer_pbpk_setup_from_prompt(prompt: str) -> dict:
    lowered = (prompt or "").lower()

    drug_name: Optional[str] = None
    m = re.search(r"pbpk\s+(?:model|simulation)\s+for\s+([a-z0-9\-]+)", lowered)
    if m:
        drug_name = m.group(1)
    if not drug_name:
        m2 = re.search(r"model\s+for\s+([a-z0-9\-]+)", lowered)
        if m2:
            drug_name = m2.group(1)
    if not drug_name:
        m3 = re.search(r"for\s+([a-z0-9\-]+)\s*\(", lowered)
        if m3:
            drug_name = m3.group(1)
    if not drug_name:
        drug_name = "compound"

    dose_mg: float = 100.0
    dose_match = re.search(r"(\d+(?:\.\d+)?)\s*mg", lowered)
    if dose_match:
        try:
            dose_mg = float(dose_match.group(1))
        except Exception:
            dose_mg = 100.0

    duration_h: float = 24.0
    dur_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)", lowered)
    if dur_match:
        try:
            duration_h = float(dur_match.group(1))
        except Exception:
            duration_h = 24.0
    elif "48 hour" in lowered or "48h" in lowered:
        duration_h = 48.0

    safe_drug = sanitize_segment(drug_name.lower()) or "compound"
    return {
        "drug_name": safe_drug,
        "dose_mg": dose_mg,
        "simulation_duration_h": duration_h,
    }


def _find_missing_claimed_files(text: str, chat_dir: Path) -> list[str]:
    if not text:
        return []

    candidates: set[str] = set()

    # Absolute paths
    for m in re.finditer(r"(/[^\s`'\"]{5,})", text):
        p = m.group(1)
        if p.startswith("/home/") or p.startswith("/data/") or p.startswith("/tmp/") or p.startswith("/var/"):
            candidates.add(p)

    # Common relative paths mentioned in reports
    for m in re.finditer(r"\b([A-Za-z0-9_\-./]+\.(?:pdf|json|csv|pkml|png|md|txt))\b", text):
        rel = m.group(1)
        if rel.startswith("http"):
            continue
        # Avoid capturing overly generic single filenames without any directory context
        candidates.add(str((chat_dir / rel).resolve()))

    missing: list[str] = []
    for p in sorted(candidates):
        try:
            if not Path(p).exists():
                missing.append(p)
        except Exception:
            continue
    return missing


def _write_workflow_report(
    chat_dir: Path,
    prompt: str,
    pbpk_enforcement: dict | None,
    literature_enforcement: dict | None,
    missing_claimed_files: list[str] | None,
) -> str | None:
    try:
        lines: list[str] = []
        lines.append("# Biomni Workflow Report")
        lines.append("")
        lines.append(f"Chat directory: `{str(chat_dir.resolve())}`")
        lines.append("")
        if prompt:
            lines.append("## Prompt")
            lines.append("```")
            lines.append(prompt[:4000])
            lines.append("```")
            lines.append("")

        lines.append("## Enforcement Status")
        lines.append("```json")
        lines.append(
            json.dumps(
                {
                    "pbpk_enforcement": pbpk_enforcement,
                    "literature_enforcement": literature_enforcement,
                    "missing_claimed_files": (missing_claimed_files or [])[:50],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        lines.append("```")
        lines.append("")

        def _list_files(title: str, rel_dir: str, patterns: tuple[str, ...]) -> None:
            base = chat_dir / rel_dir
            lines.append(f"## {title}")
            if not base.exists():
                lines.append("(missing)")
                lines.append("")
                return
            found: list[str] = []
            for pat in patterns:
                found.extend([str(p.relative_to(chat_dir)) for p in base.rglob(pat) if p.is_file()])
            found = sorted(set(found))
            if not found:
                lines.append("(none)")
                lines.append("")
                return
            for f in found[:200]:
                lines.append(f"- `{f}`")
            if len(found) > 200:
                lines.append(f"- ... ({len(found) - 200} more)")
            lines.append("")

        _list_files("Literature", "literature", ("*.pdf", "*.json", "*.txt", "*.md"))
        _list_files("Snapshots", ".", ("*_pbpk_snapshot.json", "*snapshot*.json"))
        _list_files("Simulation Outputs", "simulation_outputs", ("*.csv", "*.pkml", "*.json"))
        _list_files("Plots", "simulation_outputs/plots", ("*.png", "*.pdf", "*.svg"))

        report_path = chat_dir / "workflow_report.md"
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(report_path.resolve())
    except Exception:
        logging.exception("Failed to write workflow_report.md", exc_info=True)
        return None


def _resolve_user_id(request: Request) -> str:
    user = getattr(request.state, "_current_user", None)
    if user:
        return user.user_id
    return "default_user"


def _looks_like_snapshot(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if "Version" in payload:
        return True
    # Snapshot usually has compounds/individuals or similar building blocks
    snapshot_keys = {"Compounds", "Individuals", "Simulations", "BuildingBlocks"}
    return any(k in payload for k in snapshot_keys)


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.MULTILINE)


def _extract_snapshot_json(solution: str) -> Tuple[Optional[dict], Optional[str]]:
    if not solution:
        return None, solution

    def _attempt_parse(candidate: str) -> Optional[dict]:
        try:
            data = json.loads(candidate)
            return data if _looks_like_snapshot(data) else None
        except json.JSONDecodeError:
            return None

    # Prefer explicit code blocks
    for match in _JSON_BLOCK_RE.finditer(solution):
        candidate = match.group(1)
        data = _attempt_parse(candidate)
        if data:
            cleaned = (solution[:match.start()] + solution[match.end():]).strip()
            return data, cleaned

    trimmed = solution.strip()
    data = _attempt_parse(trimmed)
    if data:
        return data, ""

    return None, solution


def _maybe_save_snapshot(solution: str, user_id: str, chat_id: Optional[str]) -> Tuple[str, Optional[dict]]:
    if not chat_id:
        return solution, None

    snapshot_json, cleaned_solution = _extract_snapshot_json(solution)
    if not snapshot_json:
        return solution, None

    chat_dir = get_chat_dir(user_id, chat_id)

    compound_name = "snapshot"
    try:
        compounds = snapshot_json.get("Compounds") or snapshot_json.get("BuildingBlocks", {}).get("Compounds")
        if isinstance(compounds, list) and compounds:
            compound = compounds[0]
            name = compound.get("Name") if isinstance(compound, dict) else None
            if name:
                compound_name = sanitize_segment(name.lower()) or compound_name
    except Exception:
        pass

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{compound_name}_{timestamp}.json"
    file_path = chat_dir / filename

    moved_existing = False
    source_file = SNAPSHOT_REPO_DIR / filename
    if source_file.exists():
        try:
            source_file.replace(file_path)
            moved_existing = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to move snapshot %s into chat dir: %s", source_file, exc)

    if not moved_existing:
        file_path.write_text(json.dumps(snapshot_json, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        relative_path = file_path.relative_to(BIOMNI_DATA_PATH)
    except ValueError:
        relative_path = file_path.relative_to(PROJECT_ROOT)

    note = (
        "Snapshot saved in the chat files directory as "
        f"`{relative_path}`. You can download it from the Files panel."
    )
    cleaned_text = cleaned_solution.strip()
    if (cleaned_text):
        cleaned_text = f"{cleaned_text}\n\n{note}"
    else:
        cleaned_text = note

    return cleaned_text, {"filename": filename, "path": str(relative_path)}

try:
    from biomni_esqlabs_tools.snapshots.create_drug_snapshot import create_drug_snapshot
    from biomni_esqlabs_tools.snapshots.json_rag_builder import (
        rag_json_sections,
        rag_json_template,
        rag_json_answer,
        rag_json_build,
        rag_snapshot_autobuild,
    )
    from biomni_esqlabs_tools.snapshots.biomni_snapshot_tool import run_biomni_snapshot
    from biomni_esqlabs_tools.pbpk.pksim_runner import run_pksim_snapshot
    from biomni_esqlabs_tools.pbpk.pbpk_workflow import (
        create_pbpk_snapshot,
        run_pbpk_simulation,
        run_pbpk_workflow,
        get_drug_pk_parameters,
        analyze_pbpk_simulation_results,
        plot_pbpk_simulation_results,
    )
except ImportError:
    create_drug_snapshot = None
    rag_json_sections = None
    rag_json_template = None
    rag_json_answer = None
    rag_json_build = None

    run_pbpk_workflow = None
    rag_snapshot_autobuild = None
    run_biomni_snapshot = None
    run_pksim_snapshot = None
    create_pbpk_snapshot = None
    run_pbpk_simulation = None
    get_drug_pk_parameters = None
    analyze_pbpk_simulation_results = None
    plot_pbpk_simulation_results = None


REGISTERABLE_TOOLS: Dict[str, Callable[..., object]] = {}


def _register_callable(func: Optional[Callable[..., object]]) -> None:
    if func is None:
        return
    REGISTERABLE_TOOLS[func.__name__] = func


for _tool in (
    create_drug_snapshot,
    rag_json_sections,
    rag_json_template,
    rag_json_answer,
    rag_json_build,
    rag_snapshot_autobuild,
    run_biomni_snapshot,
    run_pksim_snapshot,
    create_pbpk_snapshot,
    run_pbpk_simulation,
    get_drug_pk_parameters,
    analyze_pbpk_simulation_results,
    plot_pbpk_simulation_results,
):
    _register_callable(_tool)


PRIMARY_TOOL_NAMES = {
    "vectordb",
    "create_drug_snapshot",
    "create_pbpk_snapshot",
    "run_pbpk_simulation",
    "rag_json_build",
    "run_biomni_snapshot",
}


def _pretty_label(name: str) -> str:
    return name.replace("_", " ").title()


def _doc_summary(func: Optional[Callable[..., object]]) -> str:
    if not func:
        return ""
    doc = inspect.getdoc(func)
    if not doc:
        return ""
    return doc.strip().splitlines()[0][:200]


def _build_tool_metadata() -> List[dict]:
    tools: List[dict] = [
        {
            "name": "vectordb",
            "label": "Vector DB",
            "description": "Use the Biomni vector database for broader context retrieval.",
            "category": "Core",
            "importance": "primary",
            "default_enabled": True,
        }
    ]

    for name, func in REGISTERABLE_TOOLS.items():
        tools.append(
            {
                "name": name,
                "label": _pretty_label(name),
                "description": _doc_summary(func),
                "category": (func.__module__ if func else "Custom"),
                "importance": "primary" if name in PRIMARY_TOOL_NAMES else "secondary",
                "default_enabled": name in {"create_pbpk_snapshot", "run_pbpk_simulation", "get_drug_pk_parameters"},
            }
        )

    tools.sort(key=lambda item: (0 if item.get("importance") == "primary" else 1, item["label"].lower()))
    return tools


TOOL_METADATA = _build_tool_metadata()


logger = logging.getLogger(__name__)




PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_ASSETS_DIR = PROJECT_ROOT / "biomni_esqlabs_app" / "static"
SNAPSHOT_REPO_DIR = PROJECT_ROOT / "snapshots"

app = FastAPI()
app.include_router(upload_router)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, max_age=3600)

@app.middleware("http")
async def apply_forwarded_prefix(request: Request, call_next):
    """Ensure FastAPI knows its external prefix (e.g., /biomni)."""

    forwarded_prefix = request.headers.get("x-forwarded-prefix")
    if forwarded_prefix:
        request.scope["root_path"] = forwarded_prefix.rstrip("/") or "/"
    return await call_next(request)

# Initialize the Biomni agent once when the application starts.
# Uses fast startup with static tool registry for improved performance.
agent = None
_startup_summary = None

# Check if fast startup is enabled (default: True)
_use_fast_startup = os.environ.get("BIOMNI_FAST_STARTUP", "1").lower() in ("1", "true", "yes")

if _use_fast_startup:
    try:
        from .fast_startup import initialize_agent, get_startup_summary
        agent = initialize_agent(data_path=BIOMNI_DATA_PATH)
        _startup_summary = get_startup_summary()
        if agent is None:
            logger.warning("Fast startup returned None agent")
    except Exception as exc:
        logger.warning(f"Fast startup failed, falling back to legacy init: {exc}")
        _use_fast_startup = False

if not _use_fast_startup:
    # Legacy initialization path
    try:
        if settings.OPENAI_API_KEY:
            from biomni.agent.a1 import A1
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
            agent = A1(path=str(BIOMNI_DATA_PATH))

            # Register all available tools globally once
            tools_to_register = [
                query_pubmed,
                query_scholar,
                query_arxiv,
                search_google,
                advanced_web_search,
                download_open_access_paper_pdf,
                download_pubmed_open_access_pdfs,
            ]
            if "claude" in default_config.llm.lower():
                tools_to_register.append(advanced_web_search_claude)

            tools_to_register.extend(list(REGISTERABLE_TOOLS.values()))

            for tool_func in tools_to_register:
                if tool_func is None:
                    continue
                try:
                    agent.add_tool(tool_func)
                except Exception as e:
                    logger.warning(f"Failed to register tool {getattr(tool_func, '__name__', str(tool_func))}: {e}")

        else:
            logger.warning("OpenAI API key not found. Agent not initialized.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error initializing Biomni agent: %s", exc)
        try:
            with open(BIOMNI_DATA_PATH / "init_error.log", "w") as f:
                f.write(f"Error: {exc}\n")
                import traceback
                traceback.print_exc(file=f)
        except Exception:
            pass
        agent = None


def _apply_selected_tools(selected: Optional[dict]) -> None:
    # Tool selection is intentionally ignored. The agent has access to all tools.
    return


# --- Custom UI & API ---

def _serve_authenticated_asset(asset_path: str, request: Request) -> FileResponse:
    """Return a FileResponse for assets after enforcing auth and path safety."""

    candidate_path = (STATIC_ASSETS_DIR / asset_path).resolve()
    static_root = STATIC_ASSETS_DIR.resolve()

    if not str(candidate_path).startswith(str(static_root)) or not candidate_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    return FileResponse(candidate_path)


@app.get("/app/assets/{asset_path:path}")
async def authenticated_asset(asset_path: str, request: Request):
    """Serve static assets through the authenticated /app route."""

    return _serve_authenticated_asset(asset_path, request)


@app.get("/static/{asset_path:path}")
async def legacy_static_asset(asset_path: str, request: Request):
    """Fallback for legacy /static paths behind authentication."""

    return _serve_authenticated_asset(asset_path, request)

class ChatRequest(BaseModel):
    prompt: str
    tools: Optional[dict] = None
    chat_id: Optional[str] = None

@app.get("/app", response_class=HTMLResponse)
async def app_ui(request: Request):
    """Serve the custom UI."""
    index_path = PROJECT_ROOT / "biomni_esqlabs_app" / "templates" / "index.html"
    with open(index_path, "r") as f:
        content = f.read()

    # Dynamically inject the correct root path for static assets
    root_path = request.scope.get("root_path", "").rstrip("/")
    assets_prefix = f"{root_path}/app/assets" if root_path else "/app/assets"
    assets_prefix = assets_prefix.rstrip("/") or "/app/assets"
    if not assets_prefix.startswith("/"):
        assets_prefix = "/" + assets_prefix

    replacements = (
        ('href="static/', f'href="{assets_prefix}/'),
        ('src="static/', f'src="{assets_prefix}/'),
        ('href="/static/', f'href="{assets_prefix}/'),
        ('src="/static/', f'src="{assets_prefix}/'),
    )
    for old, new in replacements:
        content = content.replace(old, new)

    # Inject the root path for frontend scripts (e.g., API calls, downloads)
    root_path_value = request.scope.get("root_path", "").rstrip("/")
    root_path_script = f'<script>window.BIOMNI_ROOT_PATH = {json.dumps(root_path_value)};</script>'
    if "</body>" in content:
        content = content.replace("</body>", f"{root_path_script}\n</body>", 1)
    else:
        content += root_path_script

    return HTMLResponse(content=content)


@app.get("/api/tools")
async def list_tools(request: Request):
    return JSONResponse({"tools": TOOL_METADATA})

@app.post("/api/chat_stream")
async def chat_stream(req: ChatRequest, request: Request):
    if not agent:
        raise HTTPException(503, "Agent not initialized")

    user_id = _resolve_user_id(request)
    chat_id = req.chat_id

    storage_chat_id = chat_id or "default_chat"
    chat_dir = get_chat_dir(user_id, storage_chat_id, create=True)

    # Ensure in-process tools default to this chat directory for all file operations.
    os.environ["BIOMNI_CHAT_DIR"] = str(chat_dir.resolve())

    _apply_selected_tools(req.tools)

    prompt_prefix = (
        "IMPORTANT: You must treat the following directory as your working directory for this chat.\n"
        f"Directory: {chat_dir.resolve()}\n"
        "The Python environment's current working directory is NOT set to this path.\n"
        f"You MUST define `CHAT_DIR = Path('{chat_dir.resolve()}')` at the start of your code "
        "and use it for ALL file operations.\n"
        "Example: `out_path = str(CHAT_DIR / 'my_file.json')`\n"
        "Do NOT write files anywhere else in the repository.\n\n"
        "IMPORTANT: You MUST execute all required subtasks in this single run. Do NOT stop after outputting only a plan/checklist. "
        "Do NOT say 'next I will...' or 'in subsequent messages'—instead, immediately continue with <execute> tool calls until completion, then provide the final <solution>.\n\n"
        "IMPORTANT: Before claiming a simulation failed or was not possible, you MUST check for existing outputs in `CHAT_DIR / 'simulation_outputs'` "
        "(e.g. a '*-Results.csv' and/or a '.pkml'). If they exist, you MUST proceed to run analysis and plotting tools on those files.\n\n"
        "IMPORTANT: If the user requests a PBPK simulation, you MUST call the PBPK simulation tool (e.g. `run_pbpk_simulation`) and you MUST NOT claim the simulation ran unless the tool returned success. "
        "When you report simulation results, you MUST include the concrete output file paths returned by the tool (e.g. `outputs.results_csv`, `outputs.pkml_file`).\n\n"
        "IMPORTANT: To enable source attribution highlighting in the UI, you MUST tag claims in your <solution> using source markers. "
        "Use the format `[[source:type|description]]text[[/source]]` (or `<source type=\"type\" info=\"description\">text</source>`). "
        "Valid types: web, literature, database, tool, internal, user. Tag each sentence or clause with the most relevant source. "
        "Examples: `[[source:literature|PMID 123456]]The trial reported...[[/source]]`, "
        "`[[source:tool|run_pbpk_simulation]]Cmax was ...[[/source]]`, "
        "`[[source:internal|general knowledge]]...[[/source]]`.\n\n"
    )
    prompt = prompt_prefix + (req.prompt or "")

    async def event_generator():
        # Helper to capture logs
        _lock = threading.Lock()
        live_logs = []

        class _Tee:
            def __init__(self, orig, sink_list, lock):
                self.orig = orig
                self.sink = sink_list
                self.lock = lock
            def write(self, data):
                try:
                    self.orig.write(data)
                    with self.lock:
                        self.sink.append(str(data))
                except Exception:
                    pass
            def flush(self):
                try:
                    self.orig.flush()
                except Exception:
                    pass

        loop = asyncio.get_running_loop()
        
        def _run_agent():
            import sys
            import contextlib
            orig_out, orig_err = sys.stdout, sys.stderr
            tee_out = _Tee(orig_out, live_logs, _lock)
            tee_err = _Tee(orig_err, live_logs, _lock)
            with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
                os.environ["BIOMNI_CHAT_DIR"] = str(chat_dir.resolve())
                os.environ.setdefault("BIOMNI_PBPK_ENGINE", "auto")
                return agent.go(prompt)

        # Start agent in thread
        future = loop.run_in_executor(None, _run_agent)
        
        last_idx = 0
        start_time = time.time()
        
        while not future.done():
            # Check logs
            with _lock:
                current_len = len(live_logs)
                new_logs = live_logs[last_idx:]
                last_idx = current_len
            
            if new_logs:
                content = "".join(new_logs)
                yield f"data: {json.dumps({'type': 'log', 'content': content})}\n\n"
            
            await asyncio.sleep(0.2)

        # Collect remaining logs
        with _lock:
            new_logs = live_logs[last_idx:]
            if new_logs:
                content = "".join(new_logs)
                yield f"data: {json.dumps({'type': 'log', 'content': content})}\n\n"

        try:
            log, final_content = await future
            
            # Parse solution like in Gradio interface
            start_tag = "<solution>"
            end_tag = "</solution>"
            solution = ""
            if final_content and start_tag in final_content:
                s = final_content.find(start_tag)
                e = final_content.find(end_tag, s + len(start_tag))
                if s != -1 and e != -1:
                    solution = final_content[s + len(start_tag):e].strip()
                else:
                    solution = final_content.split(start_tag)[-1].strip()
            else:
                solution = (final_content or "").strip()

            cleaned_solution, snapshot_info = _maybe_save_snapshot(solution, user_id, storage_chat_id)

            enforcement_note = ""
            enforcement_details: dict | None = None
            try:
                wants_pbpk = _prompt_requests_pbpk(req.prompt or "") or _prompt_requests_pbpk(prompt or "")
                if wants_pbpk and _has_pbpk_outputs(chat_dir) and not _has_pbpk_plots(chat_dir):
                    if plot_pbpk_simulation_results is None:
                        enforcement_note = "\n\n[PBPK enforcement] PBPK plot tool is not available in this runtime."
                        enforcement_details = {
                            "status": "error",
                            "reason": "plot_tool_unavailable",
                            "chat_dir": str(chat_dir.resolve()),
                        }
                    else:
                        out_dir = chat_dir / "simulation_outputs"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        try:
                            plot_res = plot_pbpk_simulation_results(
                                output_dir=str(out_dir.resolve()),
                                plot_name="pbpk_time_profile",
                                file_format="png",
                                dpi=200,
                            )
                        except Exception as exc:
                            plot_res = {"status": "error", "error": str(exc)}

                        enforcement_details = {
                            "status": "success" if plot_res.get("status") == "success" and _has_pbpk_plots(chat_dir) else "error",
                            "reason": "plot_only_enforcement",
                            "plot_result": plot_res,
                            "chat_dir": str(chat_dir.resolve()),
                        }
                        if enforcement_details["status"] == "success":
                            enforcement_note = "\n\n[PBPK enforcement] Simulation outputs were present but plots were missing; the server generated plots from existing outputs."
                        else:
                            enforcement_note = "\n\n[PBPK enforcement] Simulation outputs were present but plots were missing; the server attempted to generate plots but did not succeed (see pbpk_enforcement in run record)."

                elif wants_pbpk and not _has_pbpk_outputs(chat_dir):
                    if run_pbpk_simulation is None:
                        enforcement_note = "\n\n[PBPK enforcement] PBPK tools are not available in this runtime."
                        enforcement_details = {
                            "status": "error",
                            "reason": "pbpk_tools_unavailable",
                        }
                    else:
                        snapshot_path = _find_latest_snapshot_file(chat_dir)
                        output_dir = chat_dir / "simulation_outputs"
                        output_dir.mkdir(parents=True, exist_ok=True)

                        created_snapshot: dict | None = None
                        if snapshot_path is None and create_pbpk_snapshot is not None:
                            inferred = _infer_pbpk_setup_from_prompt(req.prompt or prompt or "")
                            out_path = chat_dir / f"{inferred['drug_name']}_pbpk_snapshot.json"
                            try:
                                created_snapshot = create_pbpk_snapshot(
                                    drug_name=inferred["drug_name"],
                                    dose_mg=float(inferred["dose_mg"]),
                                    simulation_duration_h=float(inferred["simulation_duration_h"]),
                                    out_path=str(out_path),
                                    allow_placeholders=True,
                                )
                                if created_snapshot.get("status") == "success":
                                    snapshot_path = Path(created_snapshot.get("file_path") or str(out_path))
                            except Exception as exc:
                                created_snapshot = {
                                    "status": "error",
                                    "error": f"Failed to auto-create snapshot: {exc}",
                                }

                        if snapshot_path is None:
                            enforcement_note = "\n\n[PBPK enforcement] No snapshot JSON was found in the chat directory and snapshot auto-creation was not possible."
                            enforcement_details = {
                                "status": "error",
                                "reason": "snapshot_missing",
                                "created_snapshot": created_snapshot,
                                "chat_dir": str(chat_dir.resolve()),
                            }
                        else:
                            if run_pbpk_workflow is not None:
                                workflow_result = run_pbpk_workflow(
                                    snapshot_path=str(snapshot_path),
                                    output_dir=str(output_dir),
                                    export_pkml=True,
                                    timeout_seconds=600,
                                    force_rerun=True,
                                    run_analysis=True,
                                    run_plot=True,
                                    plot_name="pbpk_time_profile",
                                    dpi=200,
                                )
                                enforcement_details = {
                                    "status": "success" if workflow_result.get("status") == "success" else "error",
                                    "snapshot_path": str(Path(snapshot_path).resolve()),
                                    "created_snapshot": created_snapshot,
                                    "workflow_result": workflow_result,
                                }
                                if workflow_result.get("status") == "success" and _has_pbpk_outputs(chat_dir):
                                    enforcement_note = "\n\n[PBPK enforcement] Simulation outputs were missing after the agent run, so the server triggered a PBPK workflow run (simulation + verification + analysis + plots)."
                                else:
                                    enforcement_note = "\n\n[PBPK enforcement] The agent did not produce simulation outputs, and the server-triggered PBPK workflow did not succeed. See pbpk_enforcement in the run record for details."
                            else:
                                sim_result = run_pbpk_simulation(
                                    snapshot_path=str(snapshot_path),
                                    output_dir=str(output_dir),
                                    export_pkml=True,
                                    force_rerun=True,
                                    timeout_seconds=600,
                                )
                                enforcement_details = {
                                    "status": "success" if sim_result.get("status") == "success" else "error",
                                    "snapshot_path": str(Path(snapshot_path).resolve()),
                                    "created_snapshot": created_snapshot,
                                    "simulation_result": sim_result,
                                }
                                if sim_result.get("status") == "success" and _has_pbpk_outputs(chat_dir):
                                    enforcement_note = "\n\n[PBPK enforcement] Simulation outputs were missing after the agent run, so the server triggered a PBPK simulation."
                                else:
                                    enforcement_note = "\n\n[PBPK enforcement] The agent did not produce simulation outputs, and the server-triggered simulation did not succeed. See pbpk_enforcement in the run record for details."
            except Exception:
                logging.exception("PBPK enforcement: unexpected error", exc_info=True)
                enforcement_note = "\n\n[PBPK enforcement] An unexpected error occurred while forcing PBPK outputs. Check server logs."
                enforcement_details = {
                    "status": "error",
                    "reason": "unexpected_exception",
                }

            literature_note = ""
            literature_details: dict | None = None
            try:
                wants_lit = _prompt_requests_literature(req.prompt or "") or _prompt_requests_literature(prompt or "")
                lit_dir = chat_dir / "literature"
                has_search_json = (lit_dir / "pubmed_search_results.json").exists()
                has_download_json = (lit_dir / "pubmed_download_report.json").exists()
                has_any_pdf = lit_dir.exists() and any(lit_dir.rglob("*.pdf"))

                missing_pmids: list[str] = []
                if wants_lit and has_search_json:
                    try:
                        search_payload_on_disk = json.loads((lit_dir / "pubmed_search_results.json").read_text(encoding="utf-8"))
                        desired_pmids = [str(p) for p in (search_payload_on_disk.get("pmids") or []) if str(p).strip()]
                    except Exception:
                        desired_pmids = []

                    attempted_pmids: set[str] = set()
                    if has_download_json:
                        try:
                            dl_payload_on_disk = json.loads((lit_dir / "pubmed_download_report.json").read_text(encoding="utf-8"))
                            for item in (dl_payload_on_disk.get("papers") or []):
                                pmid = item.get("pmid")
                                if pmid:
                                    attempted_pmids.add(str(pmid))
                        except Exception:
                            attempted_pmids = set()

                    missing_pmids = [p for p in desired_pmids if p not in attempted_pmids]

                lit_needs_enforcement = wants_lit and (
                    (not has_search_json)
                    or (not has_download_json)
                    or (not has_any_pdf)
                    or bool(missing_pmids)
                )

                if lit_needs_enforcement:
                    lit_dir.mkdir(parents=True, exist_ok=True)
                    if download_pubmed_open_access_pdfs is None:
                        literature_note = "\n\n[Literature enforcement] Literature tools are not available in this runtime."
                        literature_details = {"status": "error", "reason": "literature_tools_unavailable"}
                        try:
                            (lit_dir / "literature_enforcement_report.json").write_text(
                                json.dumps(literature_details, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                    else:
                        q = _infer_pubmed_query(req.prompt or prompt or "")
                        try:
                            search_payload = None
                            if query_pubmed is not None:
                                search_payload = query_pubmed(q, max_papers=10)
                                try:
                                    (lit_dir / "pubmed_search_results.json").write_text(
                                        json.dumps(search_payload, ensure_ascii=False, indent=2),
                                        encoding="utf-8",
                                    )
                                except Exception:
                                    pass

                            # If we already have search results, enforce downloads for every PMID listed there.
                            pmids_for_dl: list[str] | None = None
                            try:
                                payload = search_payload
                                if payload is None and (lit_dir / "pubmed_search_results.json").exists():
                                    payload = json.loads((lit_dir / "pubmed_search_results.json").read_text(encoding="utf-8"))
                                pmids_for_dl = [str(p) for p in (payload.get("pmids") or []) if str(p).strip()] if isinstance(payload, dict) else None
                            except Exception:
                                pmids_for_dl = None

                            if pmids_for_dl:
                                # Prefer missing_pmids computed from on-disk reports; otherwise attempt all.
                                pmids_arg = missing_pmids if missing_pmids else pmids_for_dl
                                dl = download_pubmed_open_access_pdfs(pmids=pmids_arg, max_papers=len(pmids_arg), output_dir=str(chat_dir))
                            else:
                                dl = download_pubmed_open_access_pdfs(query=q, max_papers=10, output_dir=str(chat_dir))
                            literature_details = {
                                "status": dl.get("status"),
                                "query": q,
                                "search": search_payload,
                                "download": dl,
                            }
                            literature_note = "\n\n[Literature enforcement] Prompt requested saving papers; server saved PubMed search results and attempted to download open-access PDFs into CHAT_DIR/literature (see run record for report_path)."
                        except Exception as exc:
                            literature_note = "\n\n[Literature enforcement] Attempted to download papers but encountered an unexpected error."
                            literature_details = {"status": "error", "query": q, "error": str(exc)}
                            try:
                                (lit_dir / "literature_enforcement_report.json").write_text(
                                    json.dumps(literature_details, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                            except Exception:
                                pass
            except Exception:
                logging.exception("Literature enforcement: unexpected error", exc_info=True)
                literature_note = "\n\n[Literature enforcement] Unexpected error while attempting to save literature. Check server logs."
                literature_details = {"status": "error", "reason": "unexpected_exception"}

            outgoing_solution = cleaned_solution + (enforcement_note or "") + (literature_note or "")
            missing_claimed_files = _find_missing_claimed_files(outgoing_solution, chat_dir)
            if missing_claimed_files:
                preview = "\n".join(f"- {p}" for p in missing_claimed_files[:50])
                outgoing_solution = (
                    outgoing_solution
                    + "\n\n[File verification] The response mentioned file paths that do not exist on disk under the current runtime.\n"
                    + preview
                )

            workflow_report_path = _write_workflow_report(
                chat_dir=chat_dir,
                prompt=req.prompt or "",
                pbpk_enforcement=enforcement_details,
                literature_enforcement=literature_details,
                missing_claimed_files=missing_claimed_files,
            )
            if workflow_report_path:
                outgoing_solution = outgoing_solution + f"\n\n[Workflow report] `{workflow_report_path}`"

            run_payload = {
                "chat_id": storage_chat_id,
                "prompt": prompt,
                "solution": outgoing_solution,
                "log": getattr(agent, "log", []),
                "records": getattr(agent, "_last_run_records", []),
                "pbpk_enforcement": enforcement_details,
                "literature_enforcement": literature_details,
                "missing_claimed_files": missing_claimed_files,
                "workflow_report_path": workflow_report_path,
                "duration_seconds": time.time() - start_time,
            }
            try:
                save_agent_run_record(user_id, storage_chat_id, run_payload)
            except Exception:
                logging.exception("Failed to persist agent run record", exc_info=True)

            yield f"data: {json.dumps({'type': 'solution', 'content': outgoing_solution})}\n\n"
            if snapshot_info:
                yield f"data: {json.dumps({'type': 'file_created', 'content': snapshot_info})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'content': f'Error: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': 'error'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Gradio Chat Interface ---
def create_chat_interface():
    """Creates the Gradio chat interface with a modern layout.

    - Primary chat shows only <solution> content.
    - Secondary "Thinking" chat shows logs and non-solution content.
    - Feedback removed.
    - File upload robustly wired to agent.add_data({file_path: description}).
    """

    def _resolve_upload_path_and_name(uploaded_file):
        """Return (file_path, original_name) from gr.File value variants."""
        if uploaded_file is None:
            return None, None
        # gr.File may return a tempfile object or a dict or a str
        path = getattr(uploaded_file, "name", None) or getattr(uploaded_file, "path", None)
        orig = getattr(uploaded_file, "orig_name", None)
        if not path and isinstance(uploaded_file, dict):
            path = uploaded_file.get("name") or uploaded_file.get("path")
            orig = uploaded_file.get("orig_name") or uploaded_file.get("name")
        if isinstance(uploaded_file, str) and not path:
            path = uploaded_file
        if path and not orig:
            orig = os.path.basename(path)
        return path, orig

    async def chat_function(message: str, sol_hist: list, think_hist: list, uploaded_file):
        """Handles the chat interaction with the Biomni agent.

        Streams agent logs into the Thinking panel with a live timer and spinner,
        and clears the input field immediately after submission.
        """
        def _ensure_tuple_history(hist: list | None) -> list[tuple[str, str | None]]:
            if not hist:
                return []
            if isinstance(hist, list) and hist and isinstance(hist[0], dict):
                out: list[tuple[str, str | None]] = []
                pending_user: str | None = None
                for item in hist:
                    role = item.get("role")
                    content = item.get("content")
                    if role == "user":
                        pending_user = str(content)
                    elif role == "assistant":
                        if pending_user is None:
                            pending_user = ""
                        out.append((pending_user, str(content) if content is not None else None))
                        pending_user = None
                if pending_user is not None:
                    out.append((pending_user, None))
                return out
            return hist

        def _set_last_assistant(hist: list[tuple[str, str | None]], content: str) -> None:
            if not hist:
                hist.append(("", content))
                return
            user_msg, _ = hist[-1]
            hist[-1] = (user_msg, content)

        sol_hist = _ensure_tuple_history(sol_hist)
        think_hist = _ensure_tuple_history(think_hist)

        if not agent:
            sol_hist.append((message, "Biomni agent is not initialized. Please check server logs."))
            think_hist.append((message, "Agent unavailable. Provide OPENAI credentials in .env and restart."))
            yield sol_hist, think_hist, "", ""
            return

        sol_hist.append((message, None))
        think_hist.append((message, None))
        prompt = message

        # Handle optional file upload and persist to BIOMNI_BASE_PATH
        if uploaded_file is not None:
            try:
                file_path, original_name = _resolve_upload_path_and_name(uploaded_file)
                description = original_name or os.path.basename(file_path)

                # Determine destination directory from settings and ensure it exists
                dest_dir = str(BIOMNI_DATA_PATH)
                os.makedirs(dest_dir, exist_ok=True)

                # Build a safe destination path and avoid collisions
                base_name = description
                name, ext = os.path.splitext(base_name)
                dest_path = os.path.join(dest_dir, base_name)
                idx = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_dir, f"{name}_{idx}{ext}")
                    idx += 1

                # Copy the uploaded file to the persistent location
                shutil.copy2(file_path, dest_path)

                abs_path = os.path.abspath(dest_path)
                agent.add_data({abs_path: description})
                prompt += f"\n\n(User has uploaded a file saved at: '{abs_path}')"
            except Exception as e:
                err = f"Error processing uploaded file: {e}"
                _set_last_assistant(think_hist, err)
                yield sol_hist, think_hist, "", ""
                return

        _set_last_assistant(sol_hist, "")
        _set_last_assistant(think_hist, "Thinking...")

        # Start live status (timer + spinner)
        start_time = time.time()
        spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame = 0

        try:
            # Helper to detect and parse rate limit waits
            def _is_rate_limit(err: Exception) -> bool:
                t = str(err).lower()
                return ("429" in t) or ("rate limit" in t) or ("throttl" in t)

            def _parse_retry_after(err: Exception) -> int | None:
                m = re.search(r"retry\s+after\s+(\d+)", str(err), re.IGNORECASE)
                if m:
                    try:
                        return int(m.group(1))
                    except Exception:
                        return None
                return None

            # Prepare a live console tee to mirror terminal output to the UI
            _lock = threading.Lock()

            class _Tee:
                def __init__(self, orig, sink_list, lock):
                    self.orig = orig
                    self.sink = sink_list
                    self.lock = lock
                def write(self, data):
                    try:
                        self.orig.write(data)
                        for line in str(data).splitlines():
                            if line:
                                with self.lock:
                                    self.sink.append(line)
                    except Exception:
                        pass
                def flush(self):
                    try:
                        self.orig.flush()
                    except Exception:
                        pass

            loop = asyncio.get_running_loop()

            def _run_agent_with_tee():
                import sys
                agent._live_console = []
                orig_out, orig_err = sys.stdout, sys.stderr
                tee_out = _Tee(orig_out, agent._live_console, _lock)
                tee_err = _Tee(orig_err, agent._live_console, _lock)
                with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
                    return agent.go(prompt)

            max_attempts = 3
            attempt = 1
            backoff = 10
            while True:
                # Run the agent in a background thread so we can stream logs
                future = loop.run_in_executor(None, _run_agent_with_tee)

                # While running, stream logs into the Thinking panel with timer
                while not future.done():
                    elapsed = time.time() - start_time
                    log_now = getattr(agent, "log", [])
                    console_now = getattr(agent, "_live_console", [])
                    combined = []
                    if isinstance(log_now, list):
                        combined.extend(log_now)
                    elif log_now:
                        combined.append(str(log_now))
                    if isinstance(console_now, list):
                        combined.extend(console_now)
                    elif console_now:
                        combined.append(str(console_now))
                    log_text = "\n".join(combined)
                    status_text = f"{spinner_frames[frame % len(spinner_frames)]} Processing… {elapsed:.1f}s"
                    frame += 1
                    _set_last_assistant(think_hist, log_text.strip() if log_text else "")
                    yield sol_hist, think_hist, status_text, ""
                    await asyncio.sleep(0.5)

                try:
                    # Completed
                    log, final_content = await future
                    break  # success
                except Exception as exec_err:  # Handle 429 at UI level with wait + retry
                    if _is_rate_limit(exec_err) and attempt < max_attempts:
                        wait_s = _parse_retry_after(exec_err) or min(backoff, 120)
                        backoff = min(int(backoff * 1.8) + 1, 120)
                        # Stream a countdown to the UI while waiting
                        for remaining in range(wait_s, 0, -1):
                            status_text = f"⏳ Rate limited. Retrying in {remaining}s…"
                            _set_last_assistant(think_hist, (think_hist[-1][1] or ""))
                            yield sol_hist, think_hist, status_text, ""
                            await asyncio.sleep(1)
                        attempt += 1
                        continue
                    else:
                        raise

            # Parse <solution> content
            start_tag = "<solution>"
            end_tag = "</solution>"
            solution = ""
            non_solution = final_content or ""
            if final_content and start_tag in final_content:
                s = final_content.find(start_tag)
                e = final_content.find(end_tag, s + len(start_tag))
                if s != -1 and e != -1:
                    solution = final_content[s + len(start_tag):e].strip()
                    non_solution = (final_content[:s] + final_content[e + len(end_tag):]).strip()
                else:
                    solution = final_content.split(start_tag)[-1].strip()
                    non_solution = ""
            else:
                solution = (final_content or "").strip()
                non_solution = ""

            # Update chats
            _set_last_assistant(sol_hist, solution)
            # Ensure the thinking log is a string
            log_text = "\n".join(log) if isinstance(log, list) else (log or "")
            thinking_text = log_text.strip()
            if non_solution:
                thinking_text = (thinking_text + "\n\n" + non_solution).strip() if thinking_text else non_solution
            _set_last_assistant(think_hist, thinking_text if thinking_text else "")

            total = time.time() - start_time
            done_status = f"✅ Done in {total:.1f}s"
            yield sol_hist, think_hist, done_status, ""

        except Exception as e:
            error_message = f"An error occurred during agent execution: {str(e)}"
            _set_last_assistant(sol_hist, error_message)
            _set_last_assistant(think_hist, error_message)
            yield sol_hist, think_hist, "", ""

    # Define the Gradio UI layout
    with gr.Blocks(
        theme=gr.themes.Soft(
            primary_hue="indigo",
            neutral_hue="slate",
        ),
        title="Biomni",
        css="""
        .gradio-container {max-width: 1400px}
        .panel {background: #0f172a10; border-radius: 12px; padding: 8px}
        .chat-title {font-size: 1.2rem; font-weight: 600; margin: 8px 0}
        """,
    ) as demo:
        gr.Markdown("### Biomni Biomedical AI Agent")

        with gr.Row():
            # Left: Solution + Thinking
            with gr.Column(scale=5):
                gr.Markdown("**Solution**", elem_classes=["chat-title"])
                solution_chat = gr.Chatbot(label=None, height=460, elem_classes=["panel"])
                gr.Markdown("**Thinking**", elem_classes=["chat-title"])
                thinking_chat = gr.Chatbot(label=None, height=240, elem_classes=["panel"])
                status_md = gr.Markdown("", elem_classes=["chat-title"])  # timer + spinner
                textbox = gr.Textbox(
                    container=True,
                    placeholder="Ask a biomedical question or describe a task...",
                    show_label=False,
                )
            # Right: Controls
            with gr.Column(scale=2, min_width=260):
                with gr.Group(elem_classes=["panel"]):
                    file_upload = gr.File(label="Upload file", file_count="single")

        # Connect the UI components to the chat function
        textbox.submit(
            chat_function,
            [textbox, solution_chat, thinking_chat, file_upload],
            [solution_chat, thinking_chat, status_md, textbox],
        )

    return demo

# --- FastAPI Endpoints ---

@app.get("/", response_class=RedirectResponse)
async def root(request: Request):
    """Send authenticated users straight to the custom UI."""
    root_path = (request.scope.get("root_path") or "").rstrip("/")
    target = f"{root_path}/app/" if root_path else "/app/"
    return RedirectResponse(url=target)


# --- Console Testing API Endpoints ---

class SnapshotRequest(BaseModel):
    """Request model for creating a PBPK snapshot."""
    drug_name: str
    dose_mg: float = 100.0
    molecular_weight: Optional[float] = None
    log_p: Optional[float] = None
    fraction_unbound: Optional[float] = None
    solubility_mg_l: Optional[float] = None
    reference_ph: float = 7.4
    individual_name: str = "HealthyAdult"
    population: str = "European_ICRP_2002"
    age_years: float = 30.0
    weight_kg: float = 70.0
    height_cm: float = 175.0
    formulation_type: str = "Formulation_Tablet_Weibull"
    simulation_duration_h: float = 24.0
    out_path: Optional[str] = None


class SimulationRequest(BaseModel):
    """Request model for running a PBPK simulation."""
    snapshot_path: str
    output_dir: Optional[str] = None
    export_pkml: bool = True
    timeout_seconds: int = 300


@app.post("/api/pbpk/snapshot")
async def api_create_snapshot(req: SnapshotRequest, request: Request):
    """
    Create a PBPK snapshot file via API.

    This endpoint allows direct creation of PK-Sim snapshot files
    for testing and automation purposes.

    Example curl command:
        curl -X POST http://localhost:8000/api/pbpk/snapshot \
            -H "Content-Type: application/json" \
            -d '{
                "drug_name": "Bupropion",
                "dose_mg": 150.0,
                "molecular_weight": 239.74,
                "log_p": 3.6,
                "fraction_unbound": 0.16,
                "solubility_mg_l": 312.0
            }'
    """
    if create_pbpk_snapshot is None:
        raise HTTPException(503, "PBPK tools not available")

    try:
        result = create_pbpk_snapshot(
            drug_name=req.drug_name,
            dose_mg=req.dose_mg,
            molecular_weight=req.molecular_weight,
            log_p=req.log_p,
            fraction_unbound=req.fraction_unbound,
            solubility_mg_l=req.solubility_mg_l,
            reference_ph=req.reference_ph,
            individual_name=req.individual_name,
            population=req.population,
            age_years=req.age_years,
            weight_kg=req.weight_kg,
            height_cm=req.height_cm,
            formulation_type=req.formulation_type,
            simulation_duration_h=req.simulation_duration_h,
            out_path=req.out_path,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Error creating snapshot")
        raise HTTPException(500, f"Error creating snapshot: {str(e)}")


@app.post("/api/pbpk/simulate")
async def api_run_simulation(req: SimulationRequest, request: Request):
    """
    Run a PBPK simulation via API.

    This endpoint runs a PK-Sim simulation from a snapshot file.
    Requires PK-Sim to be installed on the server.

    Example curl command:
        curl -X POST http://localhost:8000/api/pbpk/simulate \
            -H "Content-Type: application/json" \
            -d '{"snapshot_path": "/path/to/snapshot.json"}'
    """
    if run_pbpk_simulation is None:
        raise HTTPException(503, "PBPK simulation tools not available")

    try:
        result = run_pbpk_simulation(
            snapshot_path=req.snapshot_path,
            output_dir=req.output_dir,
            export_pkml=req.export_pkml,
            timeout_seconds=req.timeout_seconds,
        )
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Error running simulation")
        raise HTTPException(500, f"Error running simulation: {str(e)}")


@app.get("/api/pbpk/parameters/{drug_name}")
async def api_get_parameters(drug_name: str, request: Request):
    """
    Get guidance on finding PK parameters for a drug.

    This endpoint provides information about where to find
    the required pharmacokinetic parameters for PBPK modeling.

    Example curl command:
        curl http://localhost:8000/api/pbpk/parameters/Bupropion
    """
    if get_drug_pk_parameters is None:
        raise HTTPException(503, "PBPK tools not available")

    result = get_drug_pk_parameters(drug_name)
    return JSONResponse(result)


@app.get("/api/health")
async def api_health(request: Request):
    """
    Health check endpoint with startup metrics.

    Example curl command:
        curl http://localhost:8000/api/health
    """
    return JSONResponse({
        "status": "healthy" if agent is not None else "degraded",
        "agent_initialized": agent is not None,
        "startup_summary": _startup_summary,
    })


@app.get("/api/pbpk/test")
async def api_pbpk_test(request: Request):
    """
    Test endpoint that creates a sample Bupropion snapshot.

    This is a convenience endpoint for testing the PBPK workflow
    with known parameters.

    Example curl command:
        curl http://localhost:8000/api/pbpk/test
    """
    if create_pbpk_snapshot is None:
        raise HTTPException(503, "PBPK tools not available")

    # Create a test snapshot with known Bupropion parameters
    # Reference: DrugBank DB01156
    result = create_pbpk_snapshot(
        drug_name="Bupropion",
        dose_mg=150.0,
        molecular_weight=239.74,  # g/mol
        log_p=3.6,  # Lipophilicity
        fraction_unbound=0.16,  # 84% protein bound
        solubility_mg_l=312.0,  # at pH 7.4
        individual_name="HealthyAdult",
        population="European_ICRP_2002",
        simulation_duration_h=24.0,
    )

    return JSONResponse({
        "test_name": "Bupropion PBPK Snapshot",
        "result": result,
        "usage": {
            "next_step": "To run simulation, POST to /api/pbpk/simulate with the snapshot_path",
            "agent_prompt": "Create and run a PBPK simulation of 150mg Bupropion in a healthy adult population",
        }
    })


# --- Mount Gradio App ---

# Create the Gradio interface
chat_interface = create_chat_interface()

# Mount the Gradio app on the FastAPI app at the /gradio path.
app = gr.mount_gradio_app(app, chat_interface, path="/gradio")
