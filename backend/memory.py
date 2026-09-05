"""Persistent, tenant-scoped multi-turn conversation store backed by
SQLite. Unlike an in-process dict, history survives restarts and is
visible to any worker process reading the same file - a prerequisite for
running more than one API worker/replica. For true multi-instance HA behind
a load balancer, swap this module's storage for Redis/Postgres; the
get_history/append_turn/reset_session interface can stay the same.
"""
import sqlite3
import threading

from backend.config import DEFAULT_TENANT, SESSIONS_DB_PATH

MAX_HISTORY = 10
_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SESSIONS_DB_PATH, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            question TEXT NOT NULL,
            sql TEXT,
            answer TEXT NOT NULL,
            created_at REAL DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_turns_tenant_session "
        "ON conversation_turns(tenant_id, session_id, id)"
    )
    return conn


def get_history(session_id: str, tenant_id: str = DEFAULT_TENANT) -> list[dict]:
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT question, sql, answer FROM conversation_turns "
            "WHERE tenant_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
            (tenant_id, session_id, MAX_HISTORY),
        ).fetchall()
    return [{"question": q, "sql": s, "answer": a} for q, s, a in reversed(rows)]


def append_turn(session_id: str, question: str, sql: str | None, answer: str, tenant_id: str = DEFAULT_TENANT) -> None:
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO conversation_turns (tenant_id, session_id, question, sql, answer) "
            "VALUES (?, ?, ?, ?, ?)",
            (tenant_id, session_id, question, sql, answer),
        )


def reset_session(session_id: str, tenant_id: str = DEFAULT_TENANT) -> None:
    with _lock, _get_conn() as conn:
        conn.execute(
            "DELETE FROM conversation_turns WHERE tenant_id = ? AND session_id = ?",
            (tenant_id, session_id),
        )

