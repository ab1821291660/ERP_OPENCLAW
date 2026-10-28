"""Data access for evaluation datasets, cases, runs and results."""
from __future__ import annotations

import json

from ..db import utcnow
from ..util import new_id


def create_dataset(db, tenant_id: str, name: str, description: str) -> str:
    did = new_id()
    db.execute(
        "INSERT INTO eval_datasets(id,tenant_id,name,description,created_at) VALUES(?,?,?,?,?)",
        (did, tenant_id, name, description, utcnow()),
    )
    return did


def get_dataset(db, dataset_id: str, tenant_id: str):
    return db.execute(
        "SELECT * FROM eval_datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id)
    ).fetchone()


def list_datasets(db, tenant_id: str):
    return db.execute(
        """SELECT d.*, (SELECT COUNT(*) FROM eval_cases c WHERE c.dataset_id=d.id) case_count
           FROM eval_datasets d WHERE d.tenant_id=? ORDER BY d.created_at DESC""",
        (tenant_id,),
    ).fetchall()


def delete_dataset(db, dataset_id: str, tenant_id: str):
    db.execute("DELETE FROM eval_cases WHERE dataset_id IN (SELECT id FROM eval_datasets WHERE id=? AND tenant_id=?)",
               (dataset_id, tenant_id))
    db.execute("DELETE FROM eval_datasets WHERE id=? AND tenant_id=?", (dataset_id, tenant_id))


def add_case(db, dataset_id: str, text_input: str, expected: str) -> str:
    cid = new_id()
    db.execute(
        "INSERT INTO eval_cases(id,dataset_id,input,expected,created_at) VALUES(?,?,?,?,?)",
        (cid, dataset_id, text_input, expected, utcnow()),
    )
    return cid


def delete_case(db, case_id: str, tenant_id: str):
    db.execute(
        """DELETE FROM eval_cases WHERE id=? AND dataset_id IN
           (SELECT id FROM eval_datasets WHERE tenant_id=?)""",
        (case_id, tenant_id),
    )


def list_cases(db, dataset_id: str):
    return db.execute(
        "SELECT id,input,expected FROM eval_cases WHERE dataset_id=? ORDER BY rowid", (dataset_id,)
    ).fetchall()


def count_cases(db, dataset_id: str) -> int:
    return db.execute("SELECT COUNT(*) c FROM eval_cases WHERE dataset_id=?", (dataset_id,)).fetchone()["c"]


def create_run(db, tenant_id: str, dataset_id: str, agent_id: str, judge: str, total: int) -> str:
    rid = new_id()
    db.execute(
        """INSERT INTO eval_runs(id,tenant_id,dataset_id,agent_id,judge,status,total,created_at)
           VALUES(?,?,?,?,?,'pending',?,?)""",
        (rid, tenant_id, dataset_id, agent_id, judge, total, utcnow()),
    )
    return rid


def update_run_status(db, run_id: str, status: str, **fields):
    sets = ["status=?"]
    params: list = [status]
    for k, v in fields.items():
        sets.append(f"{k}=?")
        params.append(v)
    if status in ("completed", "failed"):
        sets.append("completed_at=?")
        params.append(utcnow())
    params.append(run_id)
    db.execute(f"UPDATE eval_runs SET {', '.join(sets)} WHERE id=?", params)


def get_run(db, run_id: str, tenant_id: str):
    return db.execute(
        "SELECT * FROM eval_runs WHERE id=? AND tenant_id=?", (run_id, tenant_id)
    ).fetchone()


def list_runs(db, tenant_id: str, limit: int = 50):
    return db.execute(
        "SELECT * FROM eval_runs WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?", (tenant_id, limit)
    ).fetchall()


def add_result(db, run_id: str, case_id: str, idx: int, output: str, score: float,
               reason: str, judge_error: str, latency_ms: int, tokens: dict | None,
               trace_run_id: str) -> str:
    resid = new_id()
    db.execute(
        """INSERT INTO eval_results(id,run_id,case_id,idx,output,score,judge_reason,judge_error,
           latency_ms,tokens,trace_run_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            resid, run_id, case_id, idx, output, score, reason, judge_error, latency_ms,
            json.dumps(tokens) if tokens else None, trace_run_id, utcnow(),
        ),
    )
    return resid


def link_result_trace(db, result_id: str, trace_run_id: str):
    db.execute("UPDATE eval_results SET trace_run_id=? WHERE id=?", (trace_run_id, result_id))


def list_results(db, run_id: str):
    return db.execute(
        """SELECT r.*, c.input AS case_input, c.expected AS case_expected
           FROM eval_results r JOIN eval_cases c ON c.id = r.case_id
           WHERE r.run_id=? ORDER BY r.idx""",
        (run_id,),
    ).fetchall()
