"""Conversation threads, messages and the SSE run endpoint."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models import MessageOut, RunIn, ThreadIn, ThreadOut
from ..repositories import agents as agent_repo
from ..repositories import tenants as tenant_repo
from ..repositories import threads as repo
from ..security import Context, require_member
from ..services.agent_factory import project_fs_root
from ..services.runtime_service import run_stream## ##===================================
from .deps import get_db

router = APIRouter(prefix="/threads", tags=["threads"])


def _get_thread_or_404(db, thread_id: str, tenant_id: str):
    thread = repo.get_thread(db, thread_id, tenant_id)
    if not thread:
        raise HTTPException(status_code=404, detail="对话不存在")
    return thread


@router.get("", response_model=list[ThreadOut])
def list_threads(project_id: str = "", ctx: Context = Depends(require_member), db=Depends(get_db)):
    rows = repo.list_threads(db, ctx.tenant_id, project_id=project_id or None)
    return [
        ThreadOut(
            id=r["id"], agent_id=r["agent_id"], agent_name=r["agent_name"],
            project_id=r["project_id"],
            title=r["title"], created_at=r["created_at"], updated_at=r["updated_at"],
        )
        for r in rows
    ]


@router.post("", response_model=ThreadOut, status_code=201)
def create_thread(body: ThreadIn, ctx: Context = Depends(require_member), db=Depends(get_db)):
    agent = agent_repo.get_agent(db, body.agent_id, ctx.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    # No project selected: provision a brand-new isolated project.
    # Otherwise verify the chosen project belongs to the same tenant.
    if body.project_id:
        project = tenant_repo.get_project(db, body.project_id, ctx.tenant_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        project_id = project["id"]
    else:
        project_id = tenant_repo.create_project(db, ctx.tenant_id)

    # Materialize the isolated filesystem root for this project.
    project_fs_root(ctx.tenant_id, project_id)

    tid = repo.create_thread(
        db, ctx.tenant_id, project_id, body.agent_id, ctx.user_id, body.title.strip()
    )
    db.commit()
    row = db.execute(
        """SELECT t.*, a.name agent_name FROM threads t JOIN agents a ON a.id=t.agent_id
           WHERE t.id=?""", (tid,),
    ).fetchone()
    return ThreadOut(
        id=row["id"], agent_id=row["agent_id"], agent_name=row["agent_name"],
        project_id=row["project_id"],
        title=row["title"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


@router.get("/{thread_id}/messages", response_model=list[MessageOut])
def get_messages(thread_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    _get_thread_or_404(db, thread_id, ctx.tenant_id)
    return [MessageOut(**m) for m in repo.list_messages(db, thread_id)]


@router.post("/{thread_id}/runs")
async def run_thread(thread_id: str, body: RunIn, request: Request,
                     ctx: Context = Depends(require_member), db=Depends(get_db)):
    thread = _get_thread_or_404(db, thread_id, ctx.tenant_id)
    agent = agent_repo.get_agent(db, thread["agent_id"], ctx.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    async def event_source():
        # The db connection lifetime is bound to the get_db dependency, which
        # closes only after the StreamingResponse finishes.
        async for evt in run_stream(db, ctx, thread, agent, body.content):##===================================##===================================##===================================##===================================
            yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
