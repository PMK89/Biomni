import asyncio
import os
import time
import threading
import contextlib
import shutil
import re
import gradio as gr
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware
from biomni.agent.a1 import A1
from . import auth
from .config import settings
from .upload import router as upload_router
from .db import save_run, save_upload, fetch_runs, fetch_run_by_id, fetch_uploads
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

app = FastAPI()

# Add session middleware for handling user sessions
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    max_age=3600  # Session expires after 1 hour
)

# Mount the authentication routes (e.g., /login, /callback, /logout)
app.include_router(auth.router)
app.include_router(upload_router)

# Initialize the Biomni agent once when the application starts.
# The agent's data path is relative to the project root where uvicorn is run.
agent = None
try:
    # Prefer OpenAI GPT-5 by default; requires OPENAI_API_KEY
    if settings.OPENAI_API_KEY:
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        agent = A1(
            llm="azure-gpt-5",
            path=settings.BIOMNI_BASE_PATH,
        )
    else:
        print("OpenAI API key not found. Agent not initialized.")
except Exception as e:
    print(f"Error initializing Biomni agent: {e}")
    agent = None

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

    def _linkify_paths_md(text: str) -> str:
        """Convert absolute file paths under BIOMNI_BASE_PATH into Markdown links to /download."""
        if not text:
            return text
        try:
            base = os.path.abspath(os.path.expanduser(settings.BIOMNI_BASE_PATH))
            pattern = re.compile(rf"{re.escape(base)}/[^\s'\"<>]+")
            def repl(m):
                p = os.path.abspath(m.group(0))
                name = os.path.basename(p)
                href = f"download?p={quote(p)}"
                return f"[{name}]({href})"
            return pattern.sub(repl, text)
        except Exception:
            return text

    def _build_prompt_with_history(sol_hist: list, current_prompt: str, max_messages: int = 20) -> str:
        """Build a plain-text transcript from the solution chat history plus the current prompt.

        We only use the Solution chat for history to avoid noisy Thinking logs.
        Limits to the most recent messages to control prompt size.
        """
        try:
            msgs = sol_hist or []
            # Copy and clip to last N messages
            clipped = list(msgs)[-max_messages:]
            # Replace the last user message content with current_prompt (which may include upload context)
            for i in range(len(clipped) - 1, -1, -1):
                m = clipped[i]
                if (m or {}).get("role") == "user":
                    clipped[i] = {"role": "user", "content": current_prompt}
                    break
            lines = [
                "You are continuing a conversation. Use the chat history below to maintain context.",
                "Chat history (most recent last):",
            ]
            for m in clipped:
                role = (m or {}).get("role")
                content = (m or {}).get("content") or ""
                # Skip any placeholder empty assistant messages
                if role == "assistant" and not content:
                    continue
                if role == "user":
                    lines.append(f"User: {content}")
                elif role == "assistant":
                    lines.append(f"Assistant: {content}")
            # Ensure current user prompt is the last line
            if not lines or not lines[-1].startswith("User:"):
                lines.append(f"User: {current_prompt}")
            return "\n".join(lines)
        except Exception:
            # Fallback to just the current prompt
            return current_prompt

    async def chat_function(message: str, sol_hist: list, think_hist: list, uploaded_file, request: gr.Request):
        """Handles the chat interaction with the Biomni agent.

        Streams agent logs into the Thinking panel with a live timer and spinner,
        and clears the input field immediately after submission.
        """
        # Ensure histories exist
        sol_hist = sol_hist or []
        think_hist = think_hist or []

        # Identify user from FastAPI session via Gradio request wrapper
        user_min = {}
        try:
            star_req = getattr(request, "request", None)
            if star_req is not None and hasattr(star_req, "session"):
                user_min = star_req.session.get("user") or {}
        except Exception:
            user_min = {}
        user_id = (user_min or {}).get("oid") or "anonymous"
        username = (user_min or {}).get("name") or (user_min or {}).get("preferred_username") or ""

        if not agent:
            sol_hist.append({"role": "user", "content": message})
            sol_hist.append({"role": "assistant", "content": "Biomni agent is not initialized. Please check server logs."})
            think_hist.append({"role": "assistant", "content": "Agent unavailable. Provide OPENAI credentials in .env and restart."})
            yield sol_hist, think_hist, "", "", ""
            return

        # Add user message to both chats
        sol_hist.append({"role": "user", "content": message})
        think_hist.append({"role": "user", "content": message})
        prompt = message

        # Handle optional file upload and persist to BIOMNI_BASE_PATH
        uploaded_paths = []
        if uploaded_file is not None:
            try:
                file_path, original_name = _resolve_upload_path_and_name(uploaded_file)
                description = original_name or os.path.basename(file_path)

                # Determine destination directory from settings and ensure it exists
                dest_dir = os.path.abspath(os.path.expanduser(settings.BIOMNI_BASE_PATH))
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
                uploaded_paths.append(abs_path)
            except Exception as e:
                err = f"Error processing uploaded file: {e}"
                think_hist.append({"role": "assistant", "content": err})
                yield sol_hist, think_hist, "", "", ""
                return

        # Build final prompt including conversation history
        final_prompt = _build_prompt_with_history(sol_hist, prompt, max_messages=20)

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
                    return agent.go(final_prompt)

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
                    yield sol_hist, think_hist, status_text, "", ""
                    await asyncio.sleep(0.5)

                try:
                    # Completed
                    log, final_content, audit = await future
                    break  # success
                except Exception as exec_err:  # Handle 429 at UI level with wait + retry
                    if _is_rate_limit(exec_err) and attempt < max_attempts:
                        wait_s = _parse_retry_after(exec_err) or min(backoff, 120)
                        backoff = min(int(backoff * 1.8) + 1, 120)
                        # Stream a countdown to the UI while waiting
                        for remaining in range(wait_s, 0, -1):
                            status_text = f"⏳ Rate limited. Retrying in {remaining}s…"
                            think_hist[-1]["content"] = (think_hist[-1]["content"] or "")
                            yield sol_hist, think_hist, status_text, "", ""
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

            # Update chats (linkify any output file paths)
            solution = _linkify_paths_md(solution)
            sol_hist[-1]["content"] = solution
            # Ensure the thinking log is a string
            log_text = "\n".join(log) if isinstance(log, list) else (log or "")
            thinking_text = log_text.strip()
            if non_solution:
                thinking_text = (thinking_text + "\n\n" + non_solution).strip() if thinking_text else non_solution
            thinking_text = _linkify_paths_md(thinking_text)
            think_hist[-1]["content"] = thinking_text if thinking_text else ""

            # Build Audit HTML with tooltips from APKA `internal_knowledge_audit`
            def _build_audit_html(log_lines: list[str], audit_dict: dict) -> str:
                try:
                    flagged = {}
                    for item in audit_dict.get("internal_knowledge_audit", []) or []:
                        ln = item.get("line_number")
                        just = item.get("justification", "")
                        if isinstance(ln, int) and 1 <= ln <= len(log_lines):
                            flagged[ln] = just
                    # Generate HTML, using title attr for tooltip
                    rows = [
                        '<div class="audit-container">'
                    ]
                    for i, line in enumerate(log_lines, start=1):
                        safe_line = (line or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        if i in flagged:
                            tip = (flagged[i] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                            rows.append(f'<div class="ln flagged" title="{tip}"><span class="num">{i:>4}</span> {safe_line}</div>')
                        else:
                            rows.append(f'<div class="ln"><span class="num">{i:>4}</span> {safe_line}</div>')
                    rows.append('</div>')
                    return "\n".join(rows)
                except Exception:
                    return ""

            audit_html = _build_audit_html(log if isinstance(log, list) else [], audit if isinstance(audit, dict) else {})

            # Persist this run to the per-user database
            try:
                run_id = str(uuid.uuid4())
                ts_iso = datetime.now(timezone.utc).isoformat()
                save_run(
                    user_id=user_id,
                    username=username,
                    run_id=run_id,
                    ts_iso=ts_iso,
                    prompt=prompt,
                    solution=solution,
                    thinking=thinking_text or "",
                    audit_html=audit_html or "",
                    uploads=uploaded_paths,
                )
                # Also record each upload as a separate entry, linked to this run_id
                for p in uploaded_paths:
                    try:
                        save_upload(
                            user_id=user_id,
                            username=username,
                            ts_iso=ts_iso,
                            filename=os.path.basename(p),
                            stored_path=p,
                            run_id=run_id,
                        )
                    except Exception:
                        pass
            except Exception as persist_err:
                # Do not fail UI if persistence fails; append a note to thinking panel
                note = f"[warn] Could not save run: {persist_err}"
                existing = think_hist[-1].get("content") or ""
                think_hist[-1]["content"] = (existing + ("\n\n" if existing else "") + note).strip()

            total = time.time() - start_time
            done_status = f"✅ Done in {total:.1f}s"
            yield sol_hist, think_hist, done_status, "", audit_html

        except Exception as e:
            error_message = f"An error occurred during agent execution: {str(e)}"
            sol_hist[-1]["content"] = error_message
            think_hist[-1]["content"] = error_message
            yield sol_hist, think_hist, "", "", ""

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
        .audit-container {font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size: 12px; line-height: 1.45; max-height: 700px; overflow: auto; background: #0f172a08; border-radius: 8px; padding: 8px}
        .audit-container .ln {white-space: pre-wrap; padding: 2px 6px; border-left: 3px solid transparent}
        .audit-container .ln .num {display: inline-block; width: 3em; color: #64748b}
        .audit-container .ln.flagged {background: #fef3c7; border-left-color: #f59e0b}
        .audit-container .ln.flagged:hover {background: #fde68a}
        """,
    ) as demo:
        gr.Markdown("### Biomni Biomedical AI Agent")

        with gr.Row():
            # Far Left: History Pane
            with gr.Column(scale=2, min_width=260):
                with gr.Group(elem_classes=["panel"]):
                    gr.Markdown("**History**", elem_classes=["chat-title"])
                    history_state = gr.State({})  # label -> run_id mapping
                    history_refresh = gr.Button("Refresh History")
                    run_select = gr.Dropdown(choices=[], label="Past Runs", interactive=True)
                    load_btn = gr.Button("Load Selected Run")
                    gr.Markdown("_Loaded runs are view-only; new prompts start fresh._", elem_classes=["chat-title"])
            # Middle: Solution + Thinking
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
            # Right: Controls + Audit
            with gr.Column(scale=2, min_width=260):
                with gr.Group(elem_classes=["panel"]):
                    file_upload = gr.File(label="Upload file", file_count="single")
                with gr.Group(elem_classes=["panel"]):
                    gr.Markdown("**Audit (hover for justifications)**", elem_classes=["chat-title"])
                    audit_html = gr.HTML(value="", label=None)

        # History helpers
        def _format_run_label(rec: dict) -> str:
            ts = (rec.get("ts") or "").replace("T", " ").split("+")[0].split("Z")[0]
            prompt = (rec.get("prompt") or "").strip().replace("\n", " ")
            if len(prompt) > 60:
                prompt = prompt[:57] + "..."
            rid = rec.get("run_id") or ""
            return f"{ts} · {prompt} · {rid[:8]}"

        def refresh_history(request: gr.Request):
            # Resolve current user
            user = {}
            try:
                star_req = getattr(request, "request", None)
                if star_req is not None and hasattr(star_req, "session"):
                    user = star_req.session.get("user") or {}
            except Exception:
                user = {}
            user_id = (user or {}).get("oid") or "anonymous"
            rows = fetch_runs(user_id=user_id, limit=100)
            choices = [_format_run_label(r) for r in rows]
            mapping = {choices[i]: rows[i]["run_id"] for i in range(len(rows))}
            return gr.update(choices=choices, value=None), mapping

        def load_run_into_ui(selected_label: str, mapping: dict, request: gr.Request):
            if not selected_label or not mapping:
                return [], [], "", ""
            run_id = mapping.get(selected_label)
            if not run_id:
                return [], [], "", ""
            # Resolve user
            user = {}
            try:
                star_req = getattr(request, "request", None)
                if star_req is not None and hasattr(star_req, "session"):
                    user = star_req.session.get("user") or {}
            except Exception:
                user = {}
            user_id = (user or {}).get("oid") or "anonymous"
            rec = fetch_run_by_id(user_id=user_id, run_id=run_id) or {}
            prompt = rec.get("prompt") or ""
            solution = _linkify_paths_md(rec.get("solution") or "")
            thinking = _linkify_paths_md(rec.get("thinking") or "")
            audit = rec.get("audit_html") or ""
            sol_msgs = []
            if prompt:
                sol_msgs.append({"role": "user", "content": prompt})
            if solution:
                sol_msgs.append({"role": "assistant", "content": solution})
            think_msgs = [{"role": "assistant", "content": thinking}] if thinking else []
            # Load previous prompt into textbox; new sends are fresh prompts (agent doesn't continue state)
            return sol_msgs, think_msgs, prompt, audit

        history_refresh.click(refresh_history, inputs=[], outputs=[run_select, history_state])
        load_btn.click(load_run_into_ui, inputs=[run_select, history_state], outputs=[solution_chat, thinking_chat, textbox, audit_html])

        # Initial refresh on page load
        demo.load(refresh_history, inputs=[], outputs=[run_select, history_state])

        # Connect the UI components to the chat function
        textbox.submit(
            chat_function,
            [textbox, solution_chat, thinking_chat, file_upload],
            [solution_chat, thinking_chat, status_md, textbox, audit_html],
        )

    return demo

# --- FastAPI Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Handles the root URL, showing a welcome page or redirecting to login."""
    user = request.session.get('user')
    if not user:
        base = (request.scope.get('root_path') or '').rstrip('/')
        login_url = f"{base}/login" if base else "/login"
        return RedirectResponse(url=login_url, headers={"Cache-Control": "no-store"})
    
    user_name = user.get('name', 'User')
    # Build root_path-aware absolute links (avoids any double prefix issues)
    base = (request.scope.get('root_path') or '').rstrip('/')
    href_chat = f"{base}/gradio" if base else "/gradio"
    href_logout = f"{base}/logout" if base else "/logout"
    return f"""
    <html>
        <head>
            <title>Biomni</title>
            <style>
                body {{ font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f2f5; }}
                .container {{ text-align: center; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
                h1 {{ color: #333; }}
                p {{ color: #555; }}
                a {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; }}
                a:hover {{ background-color: #0056b3; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Welcome to Biomni</h1>
                <p>You are logged in as: {user_name}</p>
                <a href="{href_chat}">Go to Chat</a>
                <br><br>
                <a href="{href_logout}">Logout</a>
            </div>
        </body>
    </html>
    """

# --- Mount Gradio App ---

# Create the Gradio interface
chat_interface = create_chat_interface()

# Mount the Gradio app on the FastAPI app at the /gradio path.
# The auth_dependency ensures that only authenticated users can access it.
app = gr.mount_gradio_app(app, chat_interface, path="/gradio", auth_dependency=auth.get_current_user)

# --- API Endpoints for history ---

def _require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@app.get("/api/runs")
async def api_list_runs(request: Request, limit: int = 50, offset: int = 0):
    user = _require_user(request)
    user_id = user.get("oid") or "anonymous"
    rows = fetch_runs(user_id=user_id, limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str, request: Request):
    user = _require_user(request)
    user_id = user.get("oid") or "anonymous"
    rec = fetch_run_by_id(user_id=user_id, run_id=run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Run not found")
    return rec


@app.get("/api/uploads")
async def api_list_uploads(request: Request, limit: int = 50, offset: int = 0):
    user = _require_user(request)
    user_id = user.get("oid") or "anonymous"
    rows = fetch_uploads(user_id=user_id, limit=limit, offset=offset)
    return {"items": rows, "count": len(rows)}


# --- Secure File Download ---

@app.get("/download")
async def download_file(p: str, request: Request):
    """Serve a file located under BIOMNI_BASE_PATH with authentication.

    Query param:
    - p: absolute file path to a file within BIOMNI_BASE_PATH
    """
    _require_user(request)  # ensure authenticated
    base = os.path.abspath(os.path.expanduser(settings.BIOMNI_BASE_PATH))
    path = os.path.abspath(p)
    # Enforce path containment
    if not (path == base or path.startswith(base + os.sep)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    fname = os.path.basename(path)
    return FileResponse(path, filename=fname, media_type="application/octet-stream")
