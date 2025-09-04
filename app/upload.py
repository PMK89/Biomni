from __future__ import annotations

import os
import time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Query
from datetime import datetime, timezone
from .db import save_upload
from .config import settings

router = APIRouter(prefix="/upload", tags=["upload"])

# Store uploads under the configured BIOMNI_BASE_PATH/uploads/{user_id} so they persist per user
_BASE_DIR = Path(os.path.abspath(os.path.expanduser(settings.BIOMNI_BASE_PATH)))
_UPLOADS_ROOT = _BASE_DIR / "uploads"
_UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("/file")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    run_id: str | None = Query(default=None, description="Optional run identifier to associate this upload with"),
) -> dict:
    """Accept a file upload and persist it under BIOMNI_BASE_PATH/uploads/{user_id}/.

    Example default: "./local_data/uploads" when using local development defaults.
    Note: Placeholder implementation; processing will be added later.
    """
    # Basic sanity checks
    if file.size is not None and file.size > 50 * 1024 * 1024:  # 50MB limit for now
        raise HTTPException(status_code=413, detail="File too large (limit 50MB)")

    # Resolve current user to determine per-user upload directory
    user = {}
    try:
        user = request.session.get("user") or {}
    except Exception:
        user = {}
    user_id = (user or {}).get("oid") or "anonymous"
    username = (user or {}).get("name") or (user or {}).get("preferred_username") or ""

    # Build per-user upload directory and safe destination filename
    user_dir = _UPLOADS_ROOT / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    sanitized = os.path.basename(file.filename or f"upload_{int(time.time())}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = user_dir / f"{ts}_{sanitized}"

    # Persist to disk
    try:
        with dest.open("wb") as f:
            chunk = await file.read()  # For small files; future: stream in chunks
            f.write(chunk)
    finally:
        await file.close()

    # Persist upload metadata per user
    try:
        ts_iso = datetime.now(timezone.utc).isoformat()
        save_upload(
            user_id=user_id,
            username=username,
            ts_iso=ts_iso,
            filename=sanitized,
            stored_path=str(dest),
            run_id=run_id,
        )
    except Exception:
        # Swallow persistence errors here; API still returns success for the file write
        pass

    return {
        "status": "accepted",
        "filename": sanitized,
        "stored_path": str(dest),
        "run_id": run_id,
        "user_id": user_id,
        "note": "Upload received and recorded.",
    }
