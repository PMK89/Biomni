import asyncio
import os
import time
import threading
import contextlib
import shutil
import re
import gradio as gr
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from biomni.agent.a1 import A1
from . import auth
from .config import settings
from .upload import router as upload_router

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
            llm="gpt-5",
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

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Handles the root URL, showing a welcome page or redirecting to login."""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/login')
    
    user_name = user.get('name', 'User')
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
                <a href="/gradio">Go to Chat</a>
                <br><br>
                <a href="/logout">Logout</a>
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
