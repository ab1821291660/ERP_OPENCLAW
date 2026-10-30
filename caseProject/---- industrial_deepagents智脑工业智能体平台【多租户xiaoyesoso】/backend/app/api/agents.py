"""Agent configuration CRUD endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from ..config import get_settings
from ..models import AgentIn, AgentOut
from ..repositories import agents as repo
from ..repositories import tenants as tenant_repo
from ..security import Context, require_admin, require_login
from ..services.agent_factory import clear_cache
from ..services.builtin_tools import PLATFORM_TOOL_MAP##===================================
from .deps import get_db

router = APIRouter(prefix="/agents", tags=["agents"])


def model_allowlist() -> list[str]:
    s = get_settings()
    return sorted({s.llm_model, s.flash_llm_model})
def _validate(payload: AgentIn):
    if payload.model and payload.model not in model_allowlist():
        raise HTTPException(status_code=422, detail=f"模型不在允许列表中：{', '.join(model_allowlist())}")
    unknown = [t for t in payload.tools if t not in PLATFORM_TOOL_MAP]
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知工具：{', '.join(unknown)}")



def _agent_payload(row) -> dict:
    d = dict(row)
    d["tools"] = json.loads(d["tools"] or "[]")
    d["sandbox_enabled"] = bool(d["sandbox_enabled"])
    d["planning_enabled"] = bool(d["planning_enabled"])
    return d



@router.get("", response_model=list[AgentOut])
def list_agents(ctx: Context = Depends(require_login), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM agents WHERE tenant_id=? ORDER BY created_at DESC", (ctx.tenant_id,)##===================================
    ).fetchall()
    return [AgentOut(**_agent_payload(r)) for r in rows]


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(body: AgentIn, ctx: Context = Depends(require_admin), db=Depends(get_db)):
    _validate(body)
    ws = tenant_repo.get_default_project(db, ctx.tenant_id)
    aid = repo.create_agent(db, ctx.tenant_id, ws["id"], body.model_dump(), ctx.user_id)##===================================
    db.commit()
    return AgentOut(**_agent_payload(db.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone()))


@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(agent_id: str, body: AgentIn, ctx: Context = Depends(require_admin), db=Depends(get_db)):
    _validate(body)
    agent = repo.get_agent(db, agent_id, ctx.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    repo.update_agent(db, agent_id, ctx.tenant_id, body.model_dump())##===================================
    clear_cache()
    db.commit()
    return AgentOut(**_agent_payload(
        db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()))


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: str, ctx: Context = Depends(require_admin), db=Depends(get_db)):
    agent = repo.get_agent(db, agent_id, ctx.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    repo.delete_agent(db, agent_id, ctx.tenant_id)##===================================
    clear_cache()
    db.commit()
