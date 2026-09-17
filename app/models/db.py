import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings

DB_FILE = Path(settings.STORAGE_PATH) / "pdfvox.db"
DB_FILE.parent.mkdir(parents=True, exist_ok=True)


def _get_conn():
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS uploads (
            file_id TEXT PRIMARY KEY,
            filename TEXT,
            path TEXT,
            total_pages INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        upload_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(uploads)").fetchall()
        }
        if "total_pages" not in upload_columns:
            conn.execute("ALTER TABLE uploads ADD COLUMN total_pages INTEGER")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            file_id TEXT,
            page INTEGER,
            status TEXT,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS generated_cache (
            cache_key TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL,
            updated_at REAL NOT NULL
            )"""
        )
    conn.close()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def save_upload(file_id: str, data: dict) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO uploads
            (file_id, filename, path, total_pages) VALUES (?, ?, ?, ?)""",
            (
                file_id,
                data.get("filename"),
                data.get("path"),
                data.get("total_pages"),
            ),
        )
    conn.close()


def update_upload_total_pages(file_id: str, total_pages: int) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE uploads SET total_pages = ? WHERE file_id = ?",
            (total_pages, file_id),
        )
    conn.close()


def get_upload(file_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE file_id = ?", (file_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def save_task(task_id: str, data: dict) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, file_id, page, status, detail, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                task_id,
                data.get("file_id"),
                data.get("page"),
                data.get("status"),
                data.get("detail"),
            ),
        )
    conn.close()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def update_task_status(task_id: str, status: str, detail: Optional[str] = None) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE tasks SET status = ?, detail = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
            (status, detail, task_id),
        )
    conn.close()


def get_generated_cache(cache_key: str):
    """Return a persisted JSON value, removing it when expired or malformed."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT payload, expires_at FROM generated_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        if float(row["expires_at"]) <= time.time():
            with conn:
                conn.execute(
                    "DELETE FROM generated_cache WHERE cache_key = ?", (cache_key,)
                )
            return None
        try:
            value = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            with conn:
                conn.execute(
                    "DELETE FROM generated_cache WHERE cache_key = ?", (cache_key,)
                )
            return None
        with conn:
            conn.execute(
                "UPDATE generated_cache SET updated_at = ? WHERE cache_key = ?",
                (time.time(), cache_key),
            )
        return value
    finally:
        conn.close()


def save_generated_cache(
    cache_key: str,
    kind: str,
    value,
    ttl_seconds: int,
    max_entries: int,
) -> None:
    """Persist a JSON value and bound the cache by expiry and LRU timestamp."""
    now = time.time()
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    conn = _get_conn()
    try:
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO generated_cache
                (cache_key, kind, payload, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (cache_key, kind, payload, now + ttl_seconds, now),
            )
            conn.execute("DELETE FROM generated_cache WHERE expires_at <= ?", (now,))
            conn.execute(
                """DELETE FROM generated_cache WHERE cache_key IN (
                SELECT cache_key FROM generated_cache
                ORDER BY updated_at DESC LIMIT -1 OFFSET ?
                )""",
                (max_entries,),
            )
    finally:
        conn.close()


# Initialize DB on import
init_db()
