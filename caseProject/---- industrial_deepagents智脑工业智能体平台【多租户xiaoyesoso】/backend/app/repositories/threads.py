"""Data access for threads and messages."""
from __future__ import annotations

import json

from ..db import utcnow
from ..util import new_id


def create_thread(db, tenant_id: str, project_id: str, agent_id: str, user_id: str, title: str) -> str:
    now = utcnow()
    tid = new_id()
    db.execute(
        """INSERT INTO threads(id,tenant_id,project_id,agent_id,user_id,title,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (tid, tenant_id, project_id, agent_id, user_id, title, now, now),
    )
    return tid


def get_thread(db, thread_id: str, tenant_id: str):
    return db.execute(
        "SELECT * FROM threads WHERE id=? AND tenant_id=?", (thread_id, tenant_id)
    ).fetchone()


def list_threads(
    db, tenant_id: str, user_id: str | None = None, project_id: str | None = None, limit: int = 30
):
    sql = """SELECT t.*, a.name AS agent_name FROM threads t
             JOIN agents a ON a.id = t.agent_id
             WHERE t.tenant_id=?"""
    params: list = [tenant_id]
    if user_id:
        sql += " AND t.user_id=?"
        params.append(user_id)
    if project_id:
        sql += " AND t.project_id=?"
        params.append(project_id)
    sql += " ORDER BY t.updated_at DESC LIMIT ?"
    params.append(limit)
    return db.execute(sql, params).fetchall()


def touch_thread(db, thread_id: str):
    db.execute("UPDATE threads SET updated_at=? WHERE id=?", (utcnow(), thread_id))


def add_message(db, thread_id: str, role: str, content: str, tool_calls=None, tokens=None) -> str:
    mid = new_id()
    db.execute(
        "INSERT INTO messages(id,thread_id,role,content,tool_calls,tokens,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            mid, thread_id, role, content,
            json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
            json.dumps(tokens) if tokens else None,
            utcnow(),
        ),
    )
    return mid


def list_messages(db, thread_id: str):
    rows = db.execute(
        "SELECT * FROM messages WHERE thread_id=? ORDER BY created_at, rowid", (thread_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tool_calls"] = json.loads(d["tool_calls"]) if d["tool_calls"] else None
        d["tokens"] = json.loads(d["tokens"]) if d["tokens"] else None
        out.append(d)
    return out
