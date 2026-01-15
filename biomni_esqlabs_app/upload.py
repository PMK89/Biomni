from __future__ import annotations

import os
import time
import shutil
import json
import zipfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Body, BackgroundTasks
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
    # Only ignore metadata/history, keep "runs" and "snapshots" visible
    ignore = {"metadata.json", "history.json"}
    if save_dir.exists():
        for item in save_dir.rglob("*"):
            if item.is_file():
                try:
                    rel = item.relative_to(save_dir)
                    if rel.parts[0] in ignore:
                        continue
                    files.append({
                        "name": str(rel),
                        "size": item.stat().st_size,
                        "modified": item.stat().st_mtime,
                    })
                except ValueError:
                    continue
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


def _safe_zip_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    members: List[zipfile.ZipInfo] = []
    for info in zf.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue
        if name.startswith("/") or name.startswith("\\"):
            raise HTTPException(status_code=400, detail="Invalid zip: absolute paths are not allowed")
        parts = Path(name).parts
        if any(p == ".." for p in parts):
            raise HTTPException(status_code=400, detail="Invalid zip: path traversal is not allowed")
        members.append(info)
    return members


def _load_json_if_exists(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _new_chat_id() -> str:
    return f"chat_{int(time.time() * 1000)}"

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


@router.get("/chat/{chat_id}/export_zip")
async def export_chat_zip(request: Request, chat_id: str, background_tasks: BackgroundTasks):
    user_id = _get_user_id(request)
    chat_dir = _get_chat_dir(user_id, chat_id, create=False)
    if not chat_dir.exists():
        raise HTTPException(status_code=404, detail="Chat not found")

    meta = _load_json_if_exists(chat_dir / "metadata.json", {"id": chat_id, "title": "(untitled)"})
    history = _load_json_if_exists(chat_dir / "history.json", [])
    runs = _load_agent_runs(user_id, chat_id)
    files = list_chat_files(user_id, chat_id)

    export_payload = {
        "schema_version": 1,
        "exported_at": time.time(),
        "user_id": user_id,
        "chat_id": chat_id,
        "metadata": meta,
        "history": history,
        "runs": runs,
        "files": files,
    }

    fd, tmp_zip_path_str = tempfile.mkstemp(prefix=f"biomni_{chat_id}_", suffix=".zip")
    os.close(fd)
    tmp_zip_path = Path(tmp_zip_path_str)

    try:
        with zipfile.ZipFile(tmp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("chat_export.json", json.dumps(export_payload, ensure_ascii=False, indent=2))
            for item in chat_dir.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(chat_dir)
                zf.write(item, arcname=str(rel))
    except Exception as e:
        try:
            tmp_zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to export chat: {str(e)}")

    background_tasks.add_task(lambda p=str(tmp_zip_path): Path(p).unlink(missing_ok=True))
    filename = f"{chat_id}.zip"
    return FileResponse(path=tmp_zip_path, filename=filename, media_type="application/zip")


@router.post("/chat/import_zip")
async def import_chat_zip(
    request: Request,
    file: UploadFile = File(...),
    chat_id: Optional[str] = Form(None),
    overwrite: bool = Form(False),
) -> Dict[str, Any]:
    user_id = _get_user_id(request)
    if file.size is not None and file.size > 250 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Zip too large (limit 250MB)")

    tmp_dir = Path(tempfile.mkdtemp(prefix="biomni_import_"))
    try:
        tmp_zip = tmp_dir / "upload.zip"
        with tmp_zip.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        with zipfile.ZipFile(tmp_zip, "r") as zf:
            members = _safe_zip_members(zf)
            zf.extractall(tmp_dir, members=[m for m in members])

        inferred_id: Optional[str] = None
        export_info_path = tmp_dir / "chat_export.json"
        if export_info_path.exists():
            try:
                export_info = _load_json_if_exists(export_info_path, {})
                inferred_id = export_info.get("chat_id") if isinstance(export_info, dict) else None
            except Exception:
                inferred_id = None

        target_chat_id = (chat_id or inferred_id or _new_chat_id()).strip()
        if not target_chat_id:
            target_chat_id = _new_chat_id()

        dest_dir = _get_chat_dir(user_id, target_chat_id, create=True)
        if dest_dir.exists() and any(dest_dir.iterdir()) and not overwrite:
            raise HTTPException(status_code=409, detail="Chat already exists. Set overwrite=true or choose another chat_id")
        if overwrite and dest_dir.exists():
            shutil.rmtree(dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)

        for item in tmp_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(tmp_dir)
            if rel.parts and rel.parts[0].startswith("upload"):
                continue
            out_path = dest_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out_path)

        meta_path = dest_dir / "metadata.json"
        if not meta_path.exists():
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"id": target_chat_id, "title": "Imported chat", "created": time.time(), "updated": time.time()}, f)

        return {"status": "ok", "chat_id": target_chat_id}
    finally:
        try:
            await file.close()
        except Exception:
            pass
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

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

@router.get("/download/{chat_id}/{filename:path}")
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
