"""Gradio-based chat UI for the Finance Assistant.
  Gradio is more responsive interface and auto-generated API.

Optimized version with:
- Better error handling
- Loading indicators
- Session management
- Auto-retry for failed requests
- Improved CSS compatibility
"""
import csv
import os
import sys
import tempfile
import time
import uuid
from typing import List, Dict, Any, Optional
from urllib.parse import quote

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration
BACKEND_URL = "http://localhost:8000"
DEFAULT_SESSION_ID = f"gradio-session-{uuid.uuid4().hex[:8]}"
MAX_RETRIES = 3
RETRY_DELAY = 1

# Create session with retry strategy
session = requests.Session()
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Custom CSS - Auto-fit layout for Gradio using elem_id hooks.
# Note: avoid forcing min-height:0/flex overrides on Gradio's internal Svelte
# wrapper chain (.main.fillable > .wrap > main.contain > .column) - doing so
# broke real-browser rendering (sidebar sections and chat panel went blank).
# Use calc()-based heights on our own elements instead, with overflow-y:auto
# as a safety net so content never becomes invisible.
CUSTOM_CSS = """
html, body { height: 100%; margin: 0; }
.gradio-container { min-height: 100vh; }
footer { display: none !important; }

#app-header { background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); color: white; padding: 0.2rem 0.75rem; margin: 0 0 0.5rem 0; border-radius: 6px; }
#app-header h1 { font-size: 0.95rem !important; margin: 0 !important; }
#app-header p { font-size: 0.65rem !important; margin: 0 !important; opacity: 0.9; }
#app-main { display: flex; gap: 0.75rem; padding: 0 0.5rem 0.5rem 0.5rem; }
#app-sidebar { width: 28%; min-width: 280px; height: calc(100vh - 40px); max-height: calc(100vh - 40px); overflow-y: auto; flex-wrap: nowrap !important; }
#app-actions { margin-top: auto !important; }
#app-chat { flex: 1; display: flex; flex-direction: column; flex-wrap: nowrap !important; }
#chatbot-box { height: calc(100vh - 150px) !important; overflow-y: auto; }
#chat-input { margin-top: 0.5rem; }

/* Subtle scrollbars */
#app-sidebar::-webkit-scrollbar, #chatbot-box::-webkit-scrollbar { width: 6px; height: 6px; }
#app-sidebar::-webkit-scrollbar-thumb, #chatbot-box::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
#app-sidebar::-webkit-scrollbar-thumb:hover, #chatbot-box::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* Button improvements */
button[type="submit"] { background: #2563eb !important; color: white !important; }

/* Compact headings */
h3 { font-size: 0.9rem !important; margin: 0 0 0.5rem 0 !important; }
"""



def get_health():
    """Check backend health and get available models."""
    try:
        r = session.get(f"{BACKEND_URL}/health", timeout=5)
        return r.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_models():
    """Get available LLM providers."""
    try:
        r = session.get(f"{BACKEND_URL}/models", timeout=5)
        data = r.json()
        providers = [p["id"] for p in data.get("providers", []) if p["configured"]]
        default_provider = data.get("default")
        if default_provider in providers:
            providers.remove(default_provider)
            providers.insert(0, default_provider)
        return providers if providers else ["qwen"]
    except Exception:
        return ["qwen", "sarvam"]


def check_backend_connection():
    """Check if backend is available."""
    try:
        r = session.get(f"{BACKEND_URL}/health", timeout=2)
        return r.status_code == 200
    except:
        return False


def format_history(history: List[Any]) -> List[Dict[str, str]]:
    """Convert history to Gradio's message format.
    
    Handles both old tuple format and new dict format.
    """
    formatted = []
    for msg in history:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            formatted.append(msg)
        elif isinstance(msg, (list, tuple)) and len(msg) == 2:
            if msg[0]:
                formatted.append({"role": "user", "content": str(msg[0])})
            if msg[1]:
                formatted.append({"role": "assistant", "content": str(msg[1])})
    return formatted


def chat(message: str, history: List[Any], model_provider: str):
    """Send chat message to backend and get response with streaming support.
    
    Args:
        message: User's input message
        history: Chat history in various formats
        model_provider: Selected LLM provider
        
    Yields:
        Updated chat history.
    """
    # Validate input
    message = message.strip()
    if not message:
        yield history
        return
    
    # Check backend availability
    if not check_backend_connection():
        formatted_history = format_history(history)
        formatted_history.append({
            "role": "assistant", 
            "content": "❌ Backend not available. Please ensure the backend is running on port 8000."
        })
        yield formatted_history
        return
    
    # Format history and add user message
    formatted_history = format_history(history)
    formatted_history.append({"role": "user", "content": message})
    
    # Show user message immediately
    yield formatted_history
    
    # Add thinking indicator
    thinking_history = formatted_history + [{"role": "assistant", "content": "🤔 Thinking..."}]
    yield thinking_history
    
    try:
        # Call backend with retry logic
        for attempt in range(MAX_RETRIES):
            try:
                r = session.post(
                    f"{BACKEND_URL}/chat",
                    json={
                        "session_id": DEFAULT_SESSION_ID,
                        "message": message,
                        "llm_provider": model_provider,
                    },
                    timeout=120,
                )
                
                if r.status_code == 200:
                    data = r.json()
                    answer = data.get("answer", "No response")
                    table = data.get("table") or []
                    sql = data.get("sql")
                    
                    # Replace thinking indicator with actual response
                    formatted_history.append({
                        "role": "assistant",
                        "content": answer + build_csv_export_link(table) + build_sql_disclosure(sql),
                    })
                    yield formatted_history
                    return
                    
                elif r.status_code == 429:
                    # Rate limited - retry
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                    else:
                        formatted_history.append({
                            "role": "assistant", 
                            "content": "❌ Rate limited. Please wait a moment and try again."
                        })
                        yield formatted_history
                        return
                else:
                    error_msg = f"❌ Error {r.status_code}: {r.text[:200]}"
                    formatted_history.append({"role": "assistant", "content": error_msg})
                    yield formatted_history
                    return
                    
            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    formatted_history.append({
                        "role": "assistant", 
                        "content": "❌ Request timed out. The backend may be busy. Please try again."
                    })
                    yield formatted_history
                    return
                    
    except Exception as e:
        formatted_history.append({
            "role": "assistant", 
            "content": f"❌ Unexpected error: {str(e)}"
        })
        yield formatted_history


def build_csv_export_link(table_data: List[Dict[str, Any]]) -> str:
    """Write one response's rows to a CSV and return its chat-local download link."""
    if not table_data:
        return ""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="finance_export_")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(table_data[0].keys()))
        writer.writeheader()
        writer.writerows(table_data)
    return f"\n\n[Export this table as CSV](/gradio_api/file={quote(path, safe='')})"


def build_sql_disclosure(sql: Optional[str]) -> str:
    """Collapsible trace of the exact SQL that produced this answer, so a
    user can verify how the result was derived without cluttering the reply."""
    if not sql:
        return ""
    escaped = sql.replace("<", "&lt;").replace(">", "&gt;")
    return (
        "\n\n<details><summary>How this was computed (SQL)</summary>\n\n"
        f"```sql\n{escaped}\n```\n</details>"
    )


def upload_data(files: Optional[List[str]]):
    """Uploads selected CSV/Excel files to the backend. The backend removes
    all previously loaded data files first, so this upload fully replaces
    the old dataset rather than merging with it, then rebuilds the database.
    """
    if not files:
        return "⚠️ Please select at least one CSV/Excel file."

    if not check_backend_connection():
        return "❌ Backend not available. Please ensure the backend is running on port 8000."

    opened = []
    try:
        file_payload = []
        for path in files:
            f = open(path, "rb")
            opened.append(f)
            file_payload.append(("files", (os.path.basename(path), f)))

        r = session.post(f"{BACKEND_URL}/upload", files=file_payload, timeout=60)
    except Exception as e:
        return f"❌ Upload error: {str(e)}"
    finally:
        for f in opened:
            f.close()

    if r.status_code != 200:
        return f"❌ Upload failed ({r.status_code}): {r.text[:200]}"

    data = r.json()
    saved = data.get("saved_files", [])
    removed = data.get("removed_files", [])
    tables = [t.get("table_name") for t in data.get("tables", []) if t.get("table_name")]

    msg = f"✅ Uploaded: {', '.join(saved)}"
    if removed:
        msg += f"\n🗑️ Replaced old file(s): {', '.join(removed)}"
    if tables:
        msg += f"\n📊 Tables loaded: {', '.join(tables)}"
    return msg


def clear_conversation():
    """Clear the conversation history and start a new session."""
    global DEFAULT_SESSION_ID
    DEFAULT_SESSION_ID = f"gradio-session-{uuid.uuid4().hex[:8]}"
    return []


def regenerate_session():
    """Generate a new session ID."""
    global DEFAULT_SESSION_ID
    DEFAULT_SESSION_ID = f"gradio-session-{uuid.uuid4().hex[:8]}"
    return DEFAULT_SESSION_ID


def create_ui():
    """Create the optimized Gradio interface with improved UX."""
    models = get_models()
    
    with gr.Blocks(
        title="Finance Assistant",
        elem_id="app-root",
    ) as demo:
        # Main layout
        with gr.Row(elem_id="app-main"):
            # Sidebar
            with gr.Column(scale=1, min_width=280, elem_id="app-sidebar"):
                # Title box lives inside the sidebar column itself so its
                # width is always exactly identical (no separate row/flex
                # ratio matching needed - which proved unreliable since
                # flex-grow distribution shifts slightly based on content).
                gr.Markdown("""
                # 💰 Finance Assistant
                Ask questions about your financial data in plain English
                """, elem_id="app-header")

                # LLM Provider selection
                with gr.Group():
                    model_dropdown = gr.Dropdown(
                        choices=models,
                        value=models[0] if models else "qwen",
                        label="LLM Provider",
                        info="Select AI model",
                    )
                
                # Clear Chat / New Session controls (pinned to bottom of sidebar)
                with gr.Group(elem_id="app-actions"):
                    clear_btn = gr.Button(
                        "Clear Chat",
                        size="sm",
                        variant="stop",
                    )
                    new_session_btn = gr.Button(
                        "New Session",
                        size="sm",
                    )
            
            # Chat Area
            with gr.Column(scale=3, elem_id="app-chat"):
                # Chatbot
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=450,
                    elem_id="chatbot-box",
                )
                
                # Input area
                with gr.Row(elem_id="chat-input"):
                    msg_input = gr.Textbox(
                        placeholder="Ask a question about your data...",
                        label="Your Question",
                        scale=9,
                        show_label=False,
                    )
                    send_btn = gr.Button(
                        "Send ➤",
                        variant="primary",
                        scale=1,
                        min_width=80,
                    )
                

        
        # Chat handlers
        send_btn.click(
            fn=chat,
            inputs=[msg_input, chatbot, model_dropdown],
            outputs=[chatbot],
        ).then(
            fn=lambda: "",
            outputs=[msg_input],
        )
        
        msg_input.submit(
            fn=chat,
            inputs=[msg_input, chatbot, model_dropdown],
            outputs=[chatbot],
        ).then(
            fn=lambda: "",
            outputs=[msg_input],
        )
        
        # Action handlers
        clear_btn.click(
            fn=clear_conversation,
            outputs=[chatbot],
        )
        
        new_session_btn.click(
            fn=regenerate_session,
        )
        
        # Load initial data
    
    return demo


def main():
    """Main entry point with argument parsing."""
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Finance Assistant Frontend")
    parser.add_argument("--port", type=int, default=8502, help="Port to run on")
    parser.add_argument("--backend", type=str, default=None, help="Backend URL")
    args = parser.parse_args()
    
    # Update global backend URL if provided
    global BACKEND_URL
    if args.backend:
        BACKEND_URL = args.backend
    
    # Check backend health
    print("🔍 Checking backend connection...")
    health = get_health()
    if health.get("status") != "ok":
        print(f"⚠️  Backend not available: {health.get('error', 'Unknown error')}")
        print(f"   Make sure the backend is running on {BACKEND_URL}")
        print("   The UI will still start, but functionality will be limited.")
    else:
        tables = health.get('tables_loaded', 0)
        print(f"✅ Backend connected: {tables} tables loaded")
    
    print(f"\n🚀 Starting Finance Assistant UI on port {args.port}...")
    print(f"   Open http://localhost:{args.port} in your browser\n")
    
    # Launch the app
    demo = create_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=args.port,
        share=False,
        show_error=True,
        inbrowser=False,
        quiet=False,
        css=CUSTOM_CSS,
        # Whitelist the OS temp dir so CSV export files (written via tempfile.mkstemp)
        # can actually be served back for download - Gradio blocks arbitrary paths otherwise.
        allowed_paths=[tempfile.gettempdir()],
    )


if __name__ == "__main__":
    main()
