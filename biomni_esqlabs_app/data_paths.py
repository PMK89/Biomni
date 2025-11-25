from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "local_data"


def _ensure_writable_base_path(raw_path: Optional[str]) -> Path:
    """Resolve a writable Biomni base directory, falling back to local_data."""

    candidate = Path(os.path.expanduser(raw_path or str(DEFAULT_DATA_DIR)))
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test_file = candidate / ".write_test"
        with test_file.open("w", encoding="utf-8") as temp:
            temp.write("ok")
        test_file.unlink(missing_ok=True)
        return candidate
    except PermissionError:
        logger.warning(
            "Biomni base path %s is not writable; falling back to %s",
            candidate,
            DEFAULT_DATA_DIR,
        )
    except OSError as exc:
        logger.warning(
            "Unable to prepare Biomni base path %s (%s); falling back to %s",
            candidate,
            exc,
            DEFAULT_DATA_DIR,
        )

    fallback = DEFAULT_DATA_DIR.resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


BIOMNI_DATA_PATH = _ensure_writable_base_path(settings.BIOMNI_BASE_PATH)
USERS_ROOT = BIOMNI_DATA_PATH / "users"
USERS_ROOT.mkdir(parents=True, exist_ok=True)


def sanitize_segment(value: Optional[str]) -> str:
    """Return a filesystem-safe segment for user/chat identifiers."""

    if not value:
        return "default"
    return "".join(c for c in value if c.isalnum() or c in "-_") or "default"


def _ensure_user_db(user_dir: Path) -> Path:
    db_path = user_dir / "db"
    if not db_path.exists():
        db_path.touch()
    return db_path


def _migrate_legacy_user_dir(sanitized_id: str, target: Path) -> None:
    """Move legacy user directories into the unified users/<id> layout."""

    legacy_candidates = [
        BIOMNI_DATA_PATH / sanitized_id,
        BIOMNI_DATA_PATH / "user_dbs" / sanitized_id,
    ]

    for candidate in legacy_candidates:
        if candidate == target:
            continue
        if candidate.exists() and candidate.is_dir():
            logger.info("Migrating legacy user data from %s to %s", candidate, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                candidate.rename(target)
            else:
                for item in candidate.iterdir():
                    dest = target / item.name
                    if dest.exists():
                        continue
                    shutil.move(str(item), str(dest))
                try:
                    candidate.rmdir()
                except OSError:
                    pass
            break


def get_user_dir(user_id: Optional[str], *, create: bool = True) -> Path:
    """Return the directory dedicated to a user (creating it + db if requested)."""

    sanitized_id = sanitize_segment(user_id)
    user_dir = USERS_ROOT / sanitized_id
    if create or user_dir.exists():
        _migrate_legacy_user_dir(sanitized_id, user_dir)
    if create:
        user_dir.mkdir(parents=True, exist_ok=True)
        _ensure_user_db(user_dir)
    return user_dir


def get_user_db_path(user_id: Optional[str], *, create: bool = True) -> Path:
    """Return the user-specific database file path."""

    user_dir = get_user_dir(user_id, create=create)
    if create:
        return _ensure_user_db(user_dir)
    return user_dir / "db"


def get_chat_dir(user_id: Optional[str], chat_id: Optional[str], *, create: bool = True) -> Path:
    """Return the chat directory within a user's folder."""

    user_dir = get_user_dir(user_id, create=create)
    chat_dir = user_dir / sanitize_segment(chat_id)
    if create:
        chat_dir.mkdir(parents=True, exist_ok=True)
    return chat_dir
