"""Trace (agent run) listing, detail and observability stats endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from ..repositories import traces as repo
from ..security import Context, require_member
from .deps import get_db

router = APIRouter(tags=["observability"])


def _run_dict(r) -> dict:
    d = dict(r)
    d["tokens"] = json.loads(d["tokens"]) if d.get("tokens") else None
    return d


@router.get("/traces")
def list_traces(
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: Context = Depends(require_member),
    db=Depends(get_db),
):
    rows = repo.list_runs(
        db, ctx.tenant_id, status=status, source=source, agent_id=agent_id,
        thread_id=thread_id, limit=limit, offset=offset,
    )
    return [_run_dict(r) for r in rows]


@router.get("/traces/{run_id}")
def get_trace(run_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    run = repo.get_run(db, run_id, ctx.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="trace 不存在")
    out = _run_dict(run)
    out["events"] = repo.list_events(db, run_id)
    return out


@router.get("/observability/stats")
def stats(ctx: Context = Depends(require_member), db=Depends(get_db)):
    return repo.stats_24h(db, ctx.tenant_id)
