import sqlite3
from pathlib import Path
from typing import Dict, Optional, Any

DB_FILE = Path("output") / "pdfvox.db"
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
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
    conn.close()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def save_upload(file_id: str, data: dict) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO uploads (file_id, filename, path) VALUES (?, ?, ?)",
            (file_id, data.get("filename"), data.get("path")),
        )
    conn.close()


def get_upload(file_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads WHERE file_id = ?", (file_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def list_uploads() -> list:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uploads ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


def list_tasks() -> list:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks ORDER BY updated_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize DB on import
init_db()
