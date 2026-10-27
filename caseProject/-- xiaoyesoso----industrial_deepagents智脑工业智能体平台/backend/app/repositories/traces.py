"""Data access for agent_runs (traces) and run_events."""
from __future__ import annotations

import json

from ..db import utcnow
from ..util import new_id


def start_run(db, *, tenant_id: str, agent_id: str, user_id: str | None, source: str,
              input_preview: str, thread_id: str | None = None,
              eval_run_id: str | None = None, eval_result_id: str | None = None) -> str:
    rid = new_id()
    db.execute(
        """INSERT INTO agent_runs(id,tenant_id,thread_id,agent_id,user_id,source,eval_run_id,
           eval_result_id,status,input_preview,created_at)
           VALUES(?,?,?,?,?,?,?,?,'running',?,?)""",
        (rid, tenant_id, thread_id, agent_id, user_id, source, eval_run_id, eval_result_id,
         input_preview, utcnow()),
    )
    return rid


def add_event(db, run_id: str, seq: int, event_type: str, name: str, data: dict):
    db.execute(
        "INSERT INTO run_events(id,run_id,seq,type,name,data,created_at) VALUES(?,?,?,?,?,?,?)",
        (new_id(), run_id, seq, event_type, name, json.dumps(data, ensure_ascii=False)[:20000], utcnow()),
    )


def finish_run(db, run_id: str, *, status: str, output_preview: str = "", latency_ms: int = 0,
               tokens: dict | None = None, error: str = "", langfuse_trace_id: str = "",
               langfuse_url: str = ""):
    db.execute(
        """UPDATE agent_runs SET status=?, output_preview=?, latency_ms=?, tokens=?, error=?,
           langfuse_trace_id=?, langfuse_url=? WHERE id=?""",
        (
            status, output_preview, latency_ms,
            json.dumps(tokens) if tokens else None, error,
            langfuse_trace_id, langfuse_url, run_id,
        ),
    )


def list_runs(db, tenant_id: str, *, status: str | None = None, source: str | None = None,
              agent_id: str | None = None, thread_id: str | None = None, limit: int = 50, offset: int = 0):
    sql = """SELECT r.*, a.name AS agent_name FROM agent_runs r
             JOIN agents a ON a.id = r.agent_id WHERE r.tenant_id=?"""
    params: list = [tenant_id]
    if status:
        sql += " AND r.status=?"
        params.append(status)
    if source:
        sql += " AND r.source=?"
        params.append(source)
    if agent_id:
        sql += " AND r.agent_id=?"
        params.append(agent_id)
    if thread_id:
        sql += " AND r.thread_id=?"
        params.append(thread_id)
    sql += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db.execute(sql, params).fetchall()


def get_run(db, run_id: str, tenant_id: str):
    return db.execute(
        "SELECT * FROM agent_runs WHERE id=? AND tenant_id=?", (run_id, tenant_id)
    ).fetchone()


def list_events(db, run_id: str):
    rows = db.execute("SELECT * FROM run_events WHERE run_id=? ORDER BY seq, rowid", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["data"] = json.loads(d["data"] or "{}")
        out.append(d)
    return out


def stats_24h(db, tenant_id: str):
    row = db.execute(
        """SELECT COUNT(*) runs,
                  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) ok,
                  AVG(latency_ms) avg_latency
           FROM agent_runs
           WHERE tenant_id=? AND created_at >= datetime('now','-1 day')""",
        (tenant_id,),
    ).fetchone()
    tok_rows = db.execute(
        "SELECT tokens FROM agent_runs WHERE tenant_id=? AND created_at >= datetime('now','-1 day') AND tokens IS NOT NULL",
        (tenant_id,),
    ).fetchall()
    total_tokens = 0
    n = 0
    for r in tok_rows:
        try:
            total_tokens += json.loads(r["tokens"]).get("total_tokens", 0)
            n += 1
        except (ValueError, TypeError):
            continue
    runs = row["runs"] or 0
    ok = row["ok"] or 0
    return {
        "runs": runs,
        "success_rate": round(ok / runs, 4) if runs else 0.0,
        "avg_latency_ms": round(row["avg_latency"] or 0, 1),
        "avg_tokens": round(total_tokens / n, 1) if n else 0,
    }
