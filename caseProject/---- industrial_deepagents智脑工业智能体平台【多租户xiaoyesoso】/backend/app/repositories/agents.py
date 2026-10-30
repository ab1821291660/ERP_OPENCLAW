"""Data access for agents."""
from __future__ import annotations

import json

from ..db import utcnow
from ..util import new_id


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["tools"] = json.loads(d.get("tools") or "[]")
    d["sandbox_enabled"] = bool(d.get("sandbox_enabled"))
    d["planning_enabled"] = bool(d.get("planning_enabled"))
    return d


def list_agents(db, tenant_id: str):
    rows = db.execute(
        "SELECT * FROM agents WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def get_agent(db, agent_id: str, tenant_id: str | None = None):
    if tenant_id is None:
        return _row(db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone())
    return _row(
        db.execute("SELECT * FROM agents WHERE id=? AND tenant_id=?", (agent_id, tenant_id)).fetchone()
    )


def create_agent(db, tenant_id: str, project_id: str, data: dict, created_by: str) -> str:
    now = utcnow()
    aid = new_id()
    db.execute(
        """INSERT INTO agents(id,tenant_id,project_id,name,description,system_prompt,model,tools,
           sandbox_enabled,planning_enabled,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            aid, tenant_id, project_id, data["name"], data.get("description", ""),
            data.get("system_prompt", ""), data.get("model", ""),
            json.dumps(data.get("tools", [])),
            1 if data.get("sandbox_enabled") else 0,
            1 if data.get("planning_enabled") else 0,
            created_by or None, now, now,
        ),
    )
    return aid


def update_agent(db, agent_id: str, tenant_id: str, data: dict):
    fields, params = [], []
    for key in ("name", "description", "system_prompt", "model"):
        if key in data:
            fields.append(f"{key}=?")
            params.append(data[key])
    if "tools" in data:
        fields.append("tools=?")
        params.append(json.dumps(data["tools"]))
    if "sandbox_enabled" in data:
        fields.append("sandbox_enabled=?")
        params.append(1 if data["sandbox_enabled"] else 0)
    if "planning_enabled" in data:
        fields.append("planning_enabled=?")
        params.append(1 if data["planning_enabled"] else 0)
    fields.append("updated_at=?")
    params.append(utcnow())
    params.extend([agent_id, tenant_id])
    db.execute(f"UPDATE agents SET {', '.join(fields)} WHERE id=? AND tenant_id=?", params)


def delete_agent(db, agent_id: str, tenant_id: str):
    db.execute("DELETE FROM agents WHERE id=? AND tenant_id=?", (agent_id, tenant_id))
