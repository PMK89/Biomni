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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import gradio as gr
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from biomni.agent.a1 import A1
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
    advanced_web_search_claude
)


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
        get_drug_pk_parameters,
    )
except ImportError:
    create_drug_snapshot = None
    rag_json_sections = None
    rag_json_template = None
    rag_json_answer = None
    rag_json_build = None
    rag_snapshot_autobuild = None
    run_biomni_snapshot = None
    run_pksim_snapshot = None
    create_pbpk_snapshot = None
    run_pbpk_simulation = None
    get_drug_pk_parameters = None


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

OIDC_OBJECT_ID_HEADER = os.getenv("OIDC_OBJECT_ID_HEADER", "x-auth-request-objectid")
OIDC_USER_HEADER = os.getenv("OIDC_USER_HEADER", "x-auth-request-user")
OIDC_EMAIL_HEADER = os.getenv("OIDC_EMAIL_HEADER", "x-auth-request-email")
OIDC_ROLES_HEADER = os.getenv("OIDC_ROLES_HEADER", "x-auth-request-groups")
FORWARDED_USER_HEADER = "x-forwarded-user"
FORWARDED_EMAIL_HEADER = "x-forwarded-email"
_GUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DISABLE_AUTH = os.getenv("BIOMNI_DISABLE_AUTH", os.getenv("DISABLE_AUTH", "0"))
DISABLE_AUTH = (DISABLE_AUTH or "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AuthenticatedUser:
    """Represents an authenticated Biomni user resolved from request headers."""

    user_id: str
    name: str
    email: Optional[str] = None
    roles: List[str] = field(default_factory=list)




def _get_header(request: Request, name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return (
        request.headers.get(name)
        or request.headers.get(name.lower())
        or request.headers.get(name.upper())
    )


def _first_non_empty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if not value:
            continue
        candidate = value.strip()
        if candidate:
            return candidate
    return None


def _is_guid(value: Optional[str]) -> bool:
    if not value:
        return False
    return bool(_GUID_PATTERN.match(value.strip()))


def _parse_roles(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    for delimiter in (";", ",", "|"):
        if delimiter in raw:
            return [piece.strip() for piece in raw.split(delimiter) if piece.strip()]
    return [raw]


def get_current_user(request: Request) -> AuthenticatedUser:
    """Resolve the current user from reverse-proxy headers, falling back to Graph."""

    cached = getattr(request.state, "_current_user", None)
    if cached is not None:
        return cached  # type: ignore[return-value]

    object_id = _first_non_empty(
        _get_header(request, OIDC_OBJECT_ID_HEADER),
        _get_header(request, "x-auth-request-oid"),
        _get_header(request, "x-ms-client-principal-id"),
    )
    email = _first_non_empty(
        _get_header(request, OIDC_EMAIL_HEADER),
        _get_header(request, FORWARDED_EMAIL_HEADER),
    )
    display_name = _first_non_empty(
        _get_header(request, OIDC_USER_HEADER),
        _get_header(request, FORWARDED_USER_HEADER),
    )
    roles = _parse_roles(_get_header(request, OIDC_ROLES_HEADER))

    user_id = None
    if object_id and _is_guid(object_id):
        user_id = object_id.lower()

    if not user_id:
        user_id = _first_non_empty(email, display_name)

    if not user_id:
        logger.warning("Authentication headers missing for path %s", request.url.path)
        raise HTTPException(status_code=401, detail="Authentication required")

    resolved_name = display_name or email or user_id
    user = AuthenticatedUser(user_id=user_id, name=resolved_name, email=email, roles=roles)
    setattr(request.state, "_current_user", user)
    return user

app = FastAPI()
if DISABLE_AUTH:
    app.include_router(upload_router)
else:
    app.include_router(upload_router, dependencies=[Depends(get_current_user)])
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, max_age=3600)

@app.middleware("http")
async def apply_forwarded_prefix(request: Request, call_next):
    """Ensure FastAPI knows its external prefix (e.g., /biomni)."""

    forwarded_prefix = request.headers.get("x-forwarded-prefix")
    if forwarded_prefix:
        request.scope["root_path"] = forwarded_prefix.rstrip("/") or "/"
    return await call_next(request)

# Initialize the Biomni agent once when the application starts.
# The agent's data path is relative to the project root where uvicorn is run.
agent = None
try:
    if settings.OPENAI_API_KEY:
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        agent = A1(path=str(BIOMNI_DATA_PATH))
        
        # Register standard literature/research tools globally once
        tools_to_register = [query_pubmed, query_scholar, query_arxiv, search_google, advanced_web_search]
        if "claude" in default_config.llm.lower():
            tools_to_register.append(advanced_web_search_claude)
            
        for tool_func in tools_to_register:
            try:
                agent.add_tool(tool_func)
            except Exception as e:
                logger.warning(f"Failed to register tool {tool_func.__name__}: {e}")
                
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
    if not selected or not agent:
        return
    for name, enabled in selected.items():
        if not enabled:
            continue
        func = REGISTERABLE_TOOLS.get(name)
        if not func:
            continue
        try:
            agent.add_tool(func)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to add tool %s: %s", name, exc)


# --- Custom UI & API ---

def _serve_authenticated_asset(asset_path: str, request: Request) -> FileResponse:
    """Return a FileResponse for assets after enforcing auth and path safety."""

    if not DISABLE_AUTH:
        get_current_user(request)

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
    if not DISABLE_AUTH:
        get_current_user(request)
    
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
    if not DISABLE_AUTH:
        get_current_user(request)
    return JSONResponse({"tools": TOOL_METADATA})

@app.post("/api/chat_stream")
async def chat_stream(req: ChatRequest, request: Request):
    if not DISABLE_AUTH:
        get_current_user(request)
    
    if not agent:
        raise HTTPException(503, "Agent not initialized")

    user_id = _resolve_user_id(request)
    chat_id = req.chat_id

    storage_chat_id = chat_id or "default_chat"
    chat_dir = get_chat_dir(user_id, storage_chat_id, create=True)

    _apply_selected_tools(req.tools)

    prompt_prefix = (
        "IMPORTANT: You must treat the following directory as your working directory for this chat.\n"
        f"Directory: {chat_dir.resolve()}\n"
        "The Python environment's current working directory is NOT set to this path.\n"
        f"You MUST define `CHAT_DIR = Path('{chat_dir.resolve()}')` at the start of your code "
        "and use it for ALL file operations.\n"
        "Example: `out_path = str(CHAT_DIR / 'my_file.json')`\n"
        "Do NOT write files anywhere else in the repository.\n\n"
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

            run_payload = {
                "chat_id": storage_chat_id,
                "prompt": prompt,
                "solution": cleaned_solution,
                "log": getattr(agent, "log", []),
                "records": getattr(agent, "_last_run_records", []),
                "duration_seconds": time.time() - start_time,
            }
            try:
                save_agent_run_record(user_id, storage_chat_id, run_payload)
            except Exception:
                logging.exception("Failed to persist agent run record", exc_info=True)

            yield f"data: {json.dumps({'type': 'solution', 'content': cleaned_solution})}\n\n"
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
        # Ensure histories exist
        sol_hist = sol_hist or []
        think_hist = think_hist or []

        if not agent:
            sol_hist.append({"role": "user", "content": message})
            sol_hist.append({"role": "assistant", "content": "Biomni agent is not initialized. Please check server logs."})
            think_hist.append({"role": "assistant", "content": "Agent unavailable. Provide OPENAI credentials in .env and restart."})
            yield sol_hist, think_hist, "", ""
            return

        # Add user message to both chats
        sol_hist.append({"role": "user", "content": message})
        think_hist.append({"role": "user", "content": message})
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
                think_hist.append({"role": "assistant", "content": err})
                yield sol_hist, think_hist, "", ""
                return

        # Placeholder assistant messages to keep UI responsive
        sol_hist.append({"role": "assistant", "content": ""})
        think_hist.append({"role": "assistant", "content": "Thinking..."})

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
                    think_hist[-1]["content"] = log_text.strip() if log_text else ""
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
                            think_hist[-1]["content"] = (think_hist[-1]["content"] or "")
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
            sol_hist[-1]["content"] = solution
            # Ensure the thinking log is a string
            log_text = "\n".join(log) if isinstance(log, list) else (log or "")
            thinking_text = log_text.strip()
            if non_solution:
                thinking_text = (thinking_text + "\n\n" + non_solution).strip() if thinking_text else non_solution
            think_hist[-1]["content"] = thinking_text if thinking_text else ""

            total = time.time() - start_time
            done_status = f"✅ Done in {total:.1f}s"
            yield sol_hist, think_hist, done_status, ""

        except Exception as e:
            error_message = f"An error occurred during agent execution: {str(e)}"
            sol_hist[-1]["content"] = error_message
            think_hist[-1]["content"] = error_message
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
                solution_chat = gr.Chatbot(label=None, height=460, type='messages', elem_classes=["panel"])
                gr.Markdown("**Thinking**", elem_classes=["chat-title"])
                thinking_chat = gr.Chatbot(label=None, height=240, type='messages', elem_classes=["panel"])
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

    if not DISABLE_AUTH:
        get_current_user(request)
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
    if not DISABLE_AUTH:
        get_current_user(request)

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
    if not DISABLE_AUTH:
        get_current_user(request)

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
    if not DISABLE_AUTH:
        get_current_user(request)

    if get_drug_pk_parameters is None:
        raise HTTPException(503, "PBPK tools not available")

    result = get_drug_pk_parameters(drug_name)
    return JSONResponse(result)


@app.get("/api/pbpk/test")
async def api_pbpk_test(request: Request):
    """
    Test endpoint that creates a sample Bupropion snapshot.

    This is a convenience endpoint for testing the PBPK workflow
    with known parameters.

    Example curl command:
        curl http://localhost:8000/api/pbpk/test
    """
    if not DISABLE_AUTH:
        get_current_user(request)

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
if DISABLE_AUTH:
    logger.warning("BIOMNI_DISABLE_AUTH=1 -> running Gradio UI without authentication (development only).")
    app = gr.mount_gradio_app(app, chat_interface, path="/gradio")
else:
    # Require authentication by leveraging the header-based resolver.
    app = gr.mount_gradio_app(app, chat_interface, path="/gradio", auth_dependency=get_current_user)
