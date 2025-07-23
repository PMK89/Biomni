import asyncio
import os
import gradio as gr
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from biomni.agent.a1 import A1
from . import auth
from .config import settings
from pypdf import PdfReader

app = FastAPI()

# Add session middleware for handling user sessions
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    max_age=3600  # Session expires after 1 hour
)

# Mount the authentication routes (e.g., /login, /callback, /logout)
app.include_router(auth.router)

# Initialize the Biomni agent once when the application starts.
# The agent's data path is relative to the project root where uvicorn is run.
agent = None
try:
    # Only initialize the agent if the required Azure credentials are provided.
    if settings.OPENAI_ENDPOINT and settings.OPENAI_API_KEY:
        # The underlying Azure client expects specific environment variables.
        os.environ["AZURE_OPENAI_API_KEY"] = settings.OPENAI_API_KEY
        os.environ["AZURE_OPENAI_ENDPOINT"] = settings.OPENAI_ENDPOINT
        agent = A1(
            llm="o3", 
            path="./biomni/data",
            base_url=settings.OPENAI_ENDPOINT,
            api_key=settings.OPENAI_API_KEY
        )
    else:
        print("Azure OpenAI credentials not found. Agent not initialized.")
except Exception as e:
    print(f"Error initializing Biomni agent: {e}")
    agent = None

# --- Gradio Chat Interface ---
def create_chat_interface():
    """Creates the Gradio chat interface."""
    
    async def chat_function(message: str, history: list, model: str, uploaded_file):
        """Handles the chat interaction with the Biomni agent."""
        if not agent:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": "Biomni agent is not initialized. Please check server logs."})
            yield history
            return

        history.append({"role": "user", "content": message})
        prompt = message

        if uploaded_file is not None:
            try:
                file_path = uploaded_file.name
                file_name = os.path.basename(file_path)

                # Use the agent's add_data method to handle the file.
                # The agent is expected to process the file from the given path.
                agent.add_data({file_path: file_name})

                # Inform the agent in the prompt that a file has been provided.
                prompt += f"\n\n(User has uploaded a file: '{file_name}')"

            except Exception as e:
                error_message = f"Error processing file '{file_name}': {e}"
                history.append({"role": "assistant", "content": error_message})
                yield history
                return



        full_response = ""
        history.append({"role": "assistant", "content": full_response})

        try:
            # agent.go() is a blocking call that returns the final log and content.
            log, final_content = agent.go(prompt)

            solution = ""
            # The final_content string contains the full response with tags.
            if "<solution>" in final_content:
                # Extract the content between the <solution> tags.
                start_tag = "<solution>"
                end_tag = "</solution>"
                start_index = final_content.find(start_tag)
                end_index = final_content.find(end_tag)
                
                if start_index != -1 and end_index != -1:
                    solution = final_content[start_index + len(start_tag):end_index].strip()
                else: # Fallback for cases with only a start tag.
                    solution = final_content.split("<solution>")[-1].strip()
            else:
                # If no solution tag is found, use the final content as a fallback.
                solution = final_content.strip()

            history[-1]["content"] = solution
            yield history

        except Exception as e:
            error_message = f"An error occurred during agent execution: {str(e)}"
            history[-1]["content"] = error_message
            yield history

    # Define the Gradio UI layout
    with gr.Blocks(theme=gr.themes.Soft(), title="Biomni") as demo:
        gr.Markdown("## Biomni Biomedical AI Agent")
        
        with gr.Row():
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(label="Chat", height=600, type='messages')
                with gr.Row():
                    textbox = gr.Textbox(
                        container=False,
                        scale=7,
                        placeholder="Enter your message or query...",
                        show_label=False,
                    )
            with gr.Column(scale=1):
                model_selector = gr.Dropdown(
                    ["o3"], # Only allow compliant Azure OpenAI models
                    label="Select Model",
                    value="o3"
                )
                file_upload = gr.File(label="Upload File")
                feedback_box = gr.Textbox(label="Feedback", placeholder="Enter your feedback here...", lines=4)
                feedback_btn = gr.Button("Submit Feedback")

        # Connect the UI components to the chat function
        textbox.submit(
            chat_function, 
            [textbox, chatbot, model_selector, file_upload], 
            chatbot
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
