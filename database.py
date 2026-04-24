import sqlite3
import os
import time

from config import DATABASE_PATH


def _get_conn() -> sqlite3.Connection:
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

        CREATE TABLE IF NOT EXISTS saved_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_saved_chat ON saved_analyses(chat_id, id);

        CREATE TABLE IF NOT EXISTS user_settings (
            chat_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL DEFAULT 'deepseek-v4-pro'
        );
    """)
    conn.commit()
    conn.close()


def save_message(chat_id: int, role: str, content: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, time.time()),
    )
    conn.commit()
    conn.close()


def get_history(chat_id: int, limit: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def clear_history(chat_id: int) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def save_analysis(chat_id: int, title: str, content: str) -> int:
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO saved_analyses (chat_id, title, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, title, content, time.time()),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_saved_analyses(chat_id: int) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, title, created_at FROM saved_analyses WHERE chat_id = ? ORDER BY id DESC",
        (chat_id,),
    ).fetchall()
    conn.close()
    return [{"id": row["id"], "title": row["title"], "created_at": row["created_at"]} for row in rows]


def get_analysis(chat_id: int, analysis_id: int) -> str | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT content FROM saved_analyses WHERE chat_id = ? AND id = ?",
        (chat_id, analysis_id),
    ).fetchone()
    conn.close()
    return row["content"] if row else None


def delete_analysis(chat_id: int, analysis_id: int) -> bool:
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM saved_analyses WHERE chat_id = ? AND id = ?",
        (chat_id, analysis_id),
    )
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_last_assistant_message(chat_id: int) -> str | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT content FROM messages WHERE chat_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    conn.close()
    return row["content"] if row else None


def get_user_model(chat_id: int) -> str | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT model FROM user_settings WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    conn.close()
    return row["model"] if row else None


def set_user_model(chat_id: int, model: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (chat_id, model) VALUES (?, ?)",
        (chat_id, model),
    )
    conn.commit()
    conn.close()
