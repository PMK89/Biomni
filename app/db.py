from __future__ import annotations

import os
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import settings

# Directory to store per-user databases
_DB_ROOT = Path(os.path.abspath(os.path.expanduser(settings.USER_DB_DIR)))
_DB_ROOT.mkdir(parents=True, exist_ok=True)


def _db_path_for_user(user_id: str) -> Path:
    safe = "".join(ch for ch in (user_id or "unknown") if ch.isalnum() or ch in ("-", "_"))
    return _DB_ROOT / f"{safe}.sqlite3"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Runs table stores conversation runs from the agent
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE,
            ts TEXT,
            user_id TEXT,
            username TEXT,
            prompt TEXT,
            solution TEXT,
            thinking TEXT,
            audit_html TEXT,
            uploads_json TEXT,
            model TEXT
        )
        """
    )
    # Backfill: add 'model' column if missing
    try:
        cur.execute("PRAGMA table_info(runs)")
        cols = [row[1] for row in cur.fetchall()]
        if "model" not in cols:
            cur.execute("ALTER TABLE runs ADD COLUMN model TEXT")
    except Exception:
        pass
    # Uploads table stores uploaded files (optionally linked to a run)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            user_id TEXT,
            username TEXT,
            filename TEXT,
            stored_path TEXT,
            run_id TEXT
        )
        """
    )
    # Feedback table stores user feedback per run
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            user_id TEXT,
            username TEXT,
            run_id TEXT,
            text TEXT
        )
        """
    )
    conn.commit()


def _connect_user_db(user_id: str) -> sqlite3.Connection:
    db_path = _db_path_for_user(user_id)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    _ensure_schema(conn)
    return conn


def save_run(
    user_id: str,
    username: Optional[str],
    run_id: str,
    ts_iso: str,
    prompt: str,
    solution: str,
    thinking: str,
    audit_html: str,
    uploads: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> None:
    """Persist a single agent run for a user."""
    uploads_json = json.dumps(uploads or [])
    with _connect_user_db(user_id) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, ts, user_id, username, prompt, solution, thinking, audit_html, uploads_json, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                ts_iso,
                user_id,
                username or "",
                prompt or "",
                solution or "",
                thinking or "",
                audit_html or "",
                uploads_json,
                model or "",
            ),
        )
        conn.commit()


def list_user_ids() -> List[str]:
    """Return list of user IDs (derived from sqlite filenames) that have a DB."""
    users: List[str] = []
    try:
        for p in _DB_ROOT.glob("*.sqlite3"):
            users.append(p.stem)
    except Exception:
        pass
    return sorted(users)


def user_run_stats(user_id: str) -> Dict[str, Any]:
    """Lightweight stats for a user: number of runs and last timestamp."""
    stats = {"user_id": user_id, "run_count": 0, "last_ts": None}
    try:
        with _connect_user_db(user_id) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM runs")
            stats["run_count"] = int(cur.fetchone()[0])
            cur = conn.execute("SELECT MAX(ts) FROM runs")
            row = cur.fetchone()
            stats["last_ts"] = row[0] if row and row[0] else None
    except Exception:
        pass
    return stats


def save_feedback(
    user_id: str,
    username: Optional[str],
    ts_iso: str,
    run_id: str,
    text: str,
) -> None:
    with _connect_user_db(user_id) as conn:
        conn.execute(
            """
            INSERT INTO feedback (ts, user_id, username, run_id, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts_iso, user_id, username or "", run_id or "", text or ""),
        )
        conn.commit()


def fetch_feedback_by_run(user_id: str, run_id: str) -> List[Dict[str, Any]]:
    with _connect_user_db(user_id) as conn:
        cur = conn.execute(
            """
            SELECT id, ts, user_id, username, run_id, text
            FROM feedback
            WHERE run_id = ?
            ORDER BY ts ASC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [{cols[i]: r[i] for i in range(len(cols))} for r in rows]


def save_upload(
    user_id: str,
    username: Optional[str],
    ts_iso: str,
    filename: str,
    stored_path: str,
    run_id: Optional[str] = None,
) -> None:
    """Record an uploaded file for a user, optionally linking to a run_id."""
    with _connect_user_db(user_id) as conn:
        conn.execute(
            """
            INSERT INTO uploads (ts, user_id, username, filename, stored_path, run_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ts_iso,
                user_id,
                username or "",
                filename or "",
                stored_path or "",
                run_id or None,
            ),
        )
        conn.commit()


def fetch_runs(user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List runs for a user, newest first."""
    with _connect_user_db(user_id) as conn:
        cur = conn.execute(
            """
            SELECT run_id, ts, user_id, username, prompt, solution, thinking, audit_html, uploads_json, model
            FROM runs
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        )
        rows = cur.fetchall()
        res: List[Dict[str, Any]] = []
        cols = [d[0] for d in cur.description]
        for r in rows:
            item = {cols[i]: r[i] for i in range(len(cols))}
            # Ensure uploads parsed
            try:
                item["uploads"] = json.loads(item.get("uploads_json") or "[]")
            except Exception:
                item["uploads"] = []
            res.append(item)
        return res


def fetch_run_by_id(user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single run and embed uploads list."""
    with _connect_user_db(user_id) as conn:
        cur = conn.execute(
            """
            SELECT run_id, ts, user_id, username, prompt, solution, thinking, audit_html, uploads_json, model
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        item = {cols[i]: row[i] for i in range(len(cols))}

        uploads = []
        try:
            uploads = json.loads(item.get("uploads_json") or "[]")
        except Exception:
            uploads = []

        try:
            cur = conn.execute(
                """
                SELECT stored_path
                FROM uploads
                WHERE run_id = ?
                ORDER BY ts ASC
                """,
                (run_id,),
            )
            extras = [r[0] for r in cur.fetchall() if r and r[0]]
            if extras:
                known = set(uploads)
                for path in extras:
                    if path not in known:
                        uploads.append(path)
                        known.add(path)
                item["uploads_json"] = json.dumps(uploads)
        except Exception:
            pass

        item["uploads"] = uploads
        return item


def fetch_uploads(user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List uploads for a user, newest first."""
    with _connect_user_db(user_id) as conn:
        cur = conn.execute(
            """
            SELECT id, ts, user_id, username, filename, stored_path, run_id
            FROM uploads
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [{cols[i]: r[i] for i in range(len(cols))} for r in rows]


def fetch_uploads_by_run(user_id: str, run_id: str) -> List[Dict[str, Any]]:
    """Return all upload rows linked to a run for the given user."""
    with _connect_user_db(user_id) as conn:
        cur = conn.execute(
            """
            SELECT id, ts, user_id, username, filename, stored_path, run_id
            FROM uploads
            WHERE run_id = ?
            ORDER BY ts DESC
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [{cols[i]: r[i] for i in range(len(cols))} for r in rows]


def delete_run(user_id: str, run_id: str) -> None:
    """Delete a run record for the given user."""
    with _connect_user_db(user_id) as conn:
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()


def delete_uploads_by_run(user_id: str, run_id: str) -> None:
    """Delete upload rows linked to the run for the given user."""
    with _connect_user_db(user_id) as conn:
        conn.execute("DELETE FROM uploads WHERE run_id = ?", (run_id,))
        conn.commit()
