from __future__ import annotations

import os
import time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/upload", tags=["upload"])

# Store uploads under biomni/data/uploads (ignored by .gitignore patterns)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_UPLOAD_DIR = _REPO_ROOT / "biomni" / "data" / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/file")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """Accept a file upload and persist it under biomni/data/uploads.

    Note: Placeholder implementation; processing will be added later.
    """
    # Basic sanity checks
    if file.size is not None and file.size > 50 * 1024 * 1024:  # 50MB limit for now
        raise HTTPException(status_code=413, detail="File too large (limit 50MB)")

    # Build a safe destination filename
    sanitized = os.path.basename(file.filename or f"upload_{int(time.time())}")
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = _UPLOAD_DIR / f"{ts}_{sanitized}"

    # Persist to disk
    try:
        with dest.open("wb") as f:
            chunk = await file.read()  # For small files; future: stream in chunks
            f.write(chunk)
    finally:
        await file.close()

    return {
        "status": "accepted",
        "filename": sanitized,
        "stored_path": str(dest),
        "note": "Upload received. Processing to be implemented in a future update.",
    }
