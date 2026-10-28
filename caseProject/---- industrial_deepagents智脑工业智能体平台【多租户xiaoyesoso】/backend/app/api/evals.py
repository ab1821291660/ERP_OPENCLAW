"""Evaluation datasets, cases and runs endpoints."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException

from ..models import (
    CaseIn,
    CaseOut,
    DatasetIn,
    DatasetOut,
    EvalRunIn,
    EvalRunOut,
)
from ..repositories import agents as agent_repo
from ..repositories import evals as repo
from ..security import Context, require_member
from ..services.eval_service import start_eval_run##===================================
from .deps import get_db

router = APIRouter(tags=["evaluation"])


# ---------- datasets ----------
@router.get("/eval/datasets", response_model=list[DatasetOut])
def list_datasets(ctx: Context = Depends(require_member), db=Depends(get_db)):
    return [DatasetOut(
        id=r["id"], name=r["name"], description=r["description"],
        case_count=r["case_count"], created_at=r["created_at"],
    ) for r in repo.list_datasets(db, ctx.tenant_id)]


@router.post("/eval/datasets", response_model=DatasetOut, status_code=201)
def create_dataset(body: DatasetIn, ctx: Context = Depends(require_member), db=Depends(get_db)):
    did = repo.create_dataset(db, ctx.tenant_id, body.name.strip(), body.description.strip())
    db.commit()
    row = db.execute("SELECT * FROM eval_datasets WHERE id=?", (did,)).fetchone()
    return DatasetOut(id=row["id"], name=row["name"], description=row["description"],
                      case_count=0, created_at=row["created_at"])


@router.get("/eval/datasets/{dataset_id}", response_model=list[CaseOut])
def list_cases(dataset_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    if not repo.get_dataset(db, dataset_id, ctx.tenant_id):
        raise HTTPException(status_code=404, detail="数据集不存在")
    return [CaseOut(id=r["id"], input=r["input"], expected=r["expected"])
            for r in repo.list_cases(db, dataset_id)]


@router.delete("/eval/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    if not repo.get_dataset(db, dataset_id, ctx.tenant_id):
        raise HTTPException(status_code=404, detail="数据集不存在")
    repo.delete_dataset(db, dataset_id, ctx.tenant_id)
    db.commit()


# ---------- cases ----------
@router.post("/eval/datasets/{dataset_id}/cases", response_model=CaseOut, status_code=201)
def add_case(dataset_id: str, body: CaseIn, ctx: Context = Depends(require_member), db=Depends(get_db)):
    if not repo.get_dataset(db, dataset_id, ctx.tenant_id):
        raise HTTPException(status_code=404, detail="数据集不存在")
    cid = repo.add_case(db, dataset_id, body.input, body.expected)
    db.commit()
    return CaseOut(id=cid, input=body.input, expected=body.expected)


@router.delete("/eval/cases/{case_id}", status_code=204)
def delete_case(case_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    owns = db.execute(
        """SELECT 1 FROM eval_cases c JOIN eval_datasets d ON d.id=c.dataset_id
           WHERE c.id=? AND d.tenant_id=?""",
        (case_id, ctx.tenant_id),
    ).fetchone()
    if not owns:
        raise HTTPException(status_code=404, detail="用例不存在")
    repo.delete_case(db, case_id, ctx.tenant_id)
    db.commit()


# ---------- runs ----------
def ________(self):pass
@router.post("/eval/runs", status_code=202)
async def create_run(body: EvalRunIn, ctx: Context = Depends(require_member), db=Depends(get_db)):
    dataset = repo.get_dataset(db, body.dataset_id, ctx.tenant_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    agent = agent_repo.get_agent(db, body.agent_id, ctx.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    total = repo.count_cases(db, body.dataset_id)
    if total == 0:
        raise HTTPException(status_code=400, detail="数据集没有用例")
    run_id = repo.create_run(db, ctx.tenant_id, body.dataset_id, body.agent_id, body.judge, total)
    db.commit()
    start_eval_run(ctx.tenant_id, run_id)##===================================##===================================##===================================##===================================
    return {"id": run_id, "status": "pending"}


@router.get("/eval/runs", response_model=list[EvalRunOut])
def list_runs(ctx: Context = Depends(require_member), db=Depends(get_db)):
    return [_run_out(r) for r in repo.list_runs(db, ctx.tenant_id)]


@router.get("/eval/runs/{run_id}", response_model=EvalRunOut)
def get_run(run_id: str, ctx: Context = Depends(require_member), db=Depends(get_db)):
    run = repo.get_run(db, run_id, ctx.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="评测 run 不存在")
    results = []
    for r in repo.list_results(db, run_id):
        results.append({
            "id": r["id"], "case_id": r["case_id"], "idx": r["idx"],
            "input": r["case_input"], "expected": r["case_expected"],
            "output": r["output"], "score": r["score"], "judge_reason": r["judge_reason"],
            "judge_error": r["judge_error"], "latency_ms": r["latency_ms"],
            "tokens": json.loads(r["tokens"]) if r["tokens"] else None,
            "trace_run_id": r["trace_run_id"],
        })
    out = _run_out(run)
    out.results = sorted(results, key=lambda x: (x["score"], x["idx"]))
    return out


def _run_out(r) -> EvalRunOut:
    return EvalRunOut(
        id=r["id"], dataset_id=r["dataset_id"], agent_id=r["agent_id"], judge=r["judge"],
        status=r["status"], total=r["total"], passed=r["passed"], mean_score=r["mean_score"],
        pass_rate=r["pass_rate"], total_ms=r["total_ms"], error=r["error"],
        created_at=r["created_at"], completed_at=r["completed_at"],
    )
