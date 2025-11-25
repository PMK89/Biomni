from __future__ import annotations

import os
import time
import shutil
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .data_paths import BIOMNI_DATA_PATH, get_chat_dir, get_user_dir

router = APIRouter(prefix="/files", tags=["files"])

def _get_user_id(request: Request) -> str:
    """Retrieve user_id from request state or default."""
    user = getattr(request.state, "_current_user", None)
    if user:
        return user.user_id
    return "default_user"

def _get_chat_dir(user_id: str, chat_id: str, *, create: bool = True) -> Path:
    """Resolve (and optionally create) the chat-specific directory."""

    return get_chat_dir(user_id, chat_id, create=create)


def list_chat_files(user_id: str, chat_id: str) -> List[dict]:
    save_dir = _get_chat_dir(user_id, chat_id)
    files: List[dict] = []
    ignore = {"metadata.json", "history.json", "runs"}
    if save_dir.exists():
        for item in save_dir.iterdir():
            if item.name in ignore:
                continue
            if item.is_file():
                files.append({
                    "name": item.name,
                    "size": item.stat().st_size,
                    "modified": item.stat().st_mtime,
                })
    return sorted(files, key=lambda x: x["modified"], reverse=True)

# --- Chat Persistence Models ---
class ChatInit(BaseModel):
    chat_id: str
    title: str

class ChatMessage(BaseModel):
    chat_id: str
    role: str
    content: str


def save_agent_run_record(user_id: str, chat_id: str, run_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a full agent run (prompt, response, tool traces) for later inspection."""

    if not run_payload:
        raise ValueError("run_payload cannot be empty")

    chat_dir = _get_chat_dir(user_id, chat_id)
    run_dir = chat_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    run_id = run_payload.get("run_id") or f"run_{int(time.time() * 1000)}"
    run_payload["run_id"] = run_id
    run_payload.setdefault("timestamp", time.time())
    run_payload.setdefault("records", [])
    run_payload.setdefault("log", [])

    run_path = run_dir / f"{run_id}.json"
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run_payload, f, ensure_ascii=False, indent=2)

    return run_payload


def _load_agent_runs(user_id: str, chat_id: str) -> List[Dict[str, Any]]:
    """Return all stored runs for a chat, newest first."""

    chat_dir = _get_chat_dir(user_id, chat_id, create=False)
    run_dir = chat_dir / "runs"
    if not run_dir.exists():
        return []

    runs: List[Dict[str, Any]] = []
    for run_file in sorted(run_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(run_file, "r", encoding="utf-8") as f:
                runs.append(json.load(f))
        except Exception:
            continue
    return runs

# --- Chat Persistence Endpoints ---

@router.get("/chats")
async def list_chats(request: Request) -> List[dict]:
    """List all chats for the current user."""
    user_id = _get_user_id(request)
    user_dir = get_user_dir(user_id, create=False)
    
    chats = []
    if user_dir.exists():
        for chat_dir in user_dir.iterdir():
            if chat_dir.is_dir():
                meta_path = chat_dir / "metadata.json"
                if meta_path.exists():
                    try:
                        with open(meta_path, "r") as f:
                            meta = json.load(f)
                            chats.append(meta)
                    except Exception:
                        continue
    # Sort by timestamp descending
    return sorted(chats, key=lambda x: x.get('timestamp', 0), reverse=True)

@router.post("/chat/init")
async def init_chat(request: Request, payload: ChatInit):
    """Create or update chat metadata."""
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, payload.chat_id)
    meta_path = chat_dir / "metadata.json"
    
    now = time.time()
    meta = {
        "id": payload.chat_id,
        "title": payload.title,
        "created": now,
        "updated": now
    }
    
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                old = json.load(f)
                meta["created"] = old.get("created", meta["created"])
                meta["updated"] = now
        except Exception:
            pass

    with open(meta_path, "w") as f:
        json.dump(meta, f)
    return {"status": "ok"}

@router.post("/chat/append")
async def append_message(request: Request, payload: ChatMessage):
    """Append a message to the chat history."""
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, payload.chat_id)
    hist_path = chat_dir / "history.json"
    
    history = []
    if hist_path.exists():
        try:
            with open(hist_path, "r") as f:
                history = json.load(f)
        except:
            pass
    
    history.append({"role": payload.role, "content": payload.content, "timestamp": time.time()})
    
    with open(hist_path, "w") as f:
        json.dump(history, f)

    # bump metadata updated timestamp
    meta_path = chat_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        meta["updated"] = time.time()
        with open(meta_path, "w") as f:
            json.dump(meta, f)
    return {"status": "ok"}

@router.get("/chat/{chat_id}/history")
async def get_history(request: Request, chat_id: str):
    """Get full history for a chat."""
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, chat_id)
    hist_path = chat_dir / "history.json"
    
    if hist_path.exists():
        try:
            with open(hist_path, "r") as f:
                return json.load(f)
        except:
            return []

@router.get("/chat/{chat_id}/metadata")
async def get_metadata(request: Request, chat_id: str):
    """Return stored metadata for a chat."""
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, chat_id, create=False)
    if not chat_dir.exists():
        raise HTTPException(status_code=404, detail="Chat not found")
    meta_path = chat_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"id": chat_id, "title": "(untitled)"}
    return []


@router.get("/chat/{chat_id}/runs")
async def get_chat_runs(request: Request, chat_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return all stored agent runs for a chat."""

    user_id = _get_user_id(request)
    runs = _load_agent_runs(user_id, chat_id)
    return {"runs": runs}

@router.delete("/chat/{chat_id}")
async def delete_chat(request: Request, chat_id: str):
    """Delete chat metadata, history, and uploaded files."""
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, chat_id, create=False)
    if chat_dir.exists():
        shutil.rmtree(chat_dir)
    return {"status": "deleted"}

# --- File Endpoints ---

@router.post("/upload")
async def upload_file(
    request: Request,
    chat_id: str = Form(...),
    file: UploadFile = File(...)
) -> dict:
    """Upload a file to a specific chat directory."""
    # Basic sanity checks
    if file.size is not None and file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (limit 50MB)")

    user_id = _get_user_id(request)
    save_dir = _get_chat_dir(user_id, chat_id)
    
    # Build destination path
    filename = os.path.basename(file.filename or f"upload_{int(time.time())}")
    dest = save_dir / filename

    # Persist to disk
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    return {
        "status": "accepted",
        "filename": filename,
        "path": str(dest)
    }

@router.get("/list/{chat_id}")
async def list_files(request: Request, chat_id: str) -> List[dict]:
    """List all files in the chat directory."""
    user_id = _get_user_id(request)
    return list_chat_files(user_id, chat_id)

@router.get("/download/{chat_id}/{filename}")
async def download_file(request: Request, chat_id: str, filename: str):
    """Download a specific file from the chat directory."""
    user_id = _get_user_id(request)
    save_dir = _get_chat_dir(user_id, chat_id)
    file_path = save_dir / filename
    
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(
        path=file_path, 
        filename=filename,
        media_type='application/octet-stream'
    )
