"""Evaluation scoring and background run execution."""
from __future__ import annotations

import asyncio
import json
import re
import time

from ..config import get_settings
from ..db import connect
from ..repositories import agents as agent_repo##========
from ..repositories import evals as eval_repo##--------
from .agent_factory import build_judge_model
from .runtime_service import run_agent_once##===================================

PASS_THRESHOLD = 0.6
_tenant_locks: dict[str, asyncio.Lock] = {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def score_contains(output: str, expected: str) -> tuple[float, str]:
    keywords = [k.strip().lower() for k in expected.split("|") if k.strip()]
    if not keywords:
        return 0.0, "expected is empty"
    missing = [k for k in keywords if k not in (output or "").lower()]
    if missing:
        return 0.0, f"missing keywords: {', '.join(missing)}"
    return 1.0, "all keywords found"


def score_exact(output: str, expected: str) -> tuple[float, str]:
    ok = _normalize(output) == _normalize(expected)
    return (1.0 if ok else 0.0), ("exact match" if ok else "normalized text differs")


JUDGE_PROMPT = """You are a strict grading judge. Compare the model OUTPUT with EXPECTED answer for the INPUT.
Return ONLY a JSON object, no prose, in this exact shape:
{"score": <float between 0 and 1>, "reason": "<one short sentence>"}
Scoring: 1.0 fully correct, 0.5 partially correct, 0 wrong or irrelevant."""

def parse_judge_json(text: str) -> tuple[float, str]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    payload = json.loads(match.group(0) if match else text)
    ##
    score = float(payload.get("score", 0))
    score = max(0.0, min(1.0, score))
    reason = str(payload.get("reason", ""))[:500]
    return score, reason

async def score_llm_judge(judge_model, text_input: str, expected: str, output: str) -> tuple[float, str, str]:
    """Returns (score, reason, judge_error). Judge failures score 0 but never raise."""
    if not output:
        return 0.0, "", "empty agent output"
    user_msg = (
        f"INPUT:\n{text_input}\n\nEXPECTED:\n{expected}\n\nOUTPUT:\n{output[:6000]}"
    )
    try:
        resp = await judge_model.ainvoke([
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": user_msg},
        ])
        content = resp.content if hasattr(resp, "content") else str(resp)
        score, reason = parse_judge_json(content)##===================================
        return score, reason, ""
    except Exception as exc:  # noqa: BLE001 - one failed judgment must not abort the run
        return 0.0, "", f"{type(exc).__name__}: {exc}"[:500]


def ________(self):pass
async def _run_eval(eval_run_id: str) -> None:
    db = connect()
    try:
        run = db.execute("SELECT * FROM eval_runs WHERE id=?", (eval_run_id,)).fetchone()##========
        if not run:
            return
        tenant_id = run["tenant_id"]
        cases = db.execute(##========
            """SELECT c.* FROM eval_cases c JOIN eval_datasets d ON d.id=c.dataset_id
               WHERE c.dataset_id=? AND d.tenant_id=? ORDER BY c.rowid""",
            (run["dataset_id"], tenant_id),
        ).fetchall()


        agent = agent_repo.get_agent(db, run["agent_id"], tenant_id)##========
        if not agent:
            eval_repo.update_run_status(db, eval_run_id, "failed", error="agent not found")##--------
            db.commit()
            return
        project_id = agent["project_id"]
        eval_repo.update_run_status(db, eval_run_id, "running")##--------
        db.commit()


        judge_model = None
        if run["judge"] == "llm_judge":
            try:
                judge_model = build_judge_model()##===================================
            except Exception as exc:  # noqa: BLE001
                eval_repo.update_run_status(db, eval_run_id, "failed",##--------
                                            error=f"judge model unavailable: {exc}")
                db.commit()
                return




        started = time.monotonic()
        scores, passed = [], 0
        for idx, case in enumerate(cases):##===================================
            result = await run_agent_once(##===================================##===================================##===================================##===================================
                db, tenant_id=tenant_id, project_id=project_id,
                agent=agent,
                user_id=None, content=case["input"], source="evaluation", eval_run_id=eval_run_id,
            )
            judge_error = ""
            if result.error:
                score, reason = 0.0, f"agent error: {result.error}"
                judge_error = result.error
            elif run["judge"] == "contains":
                score, reason = score_contains(result.output, case["expected"])##===================================
            elif run["judge"] == "exact":
                score, reason = score_exact(result.output, case["expected"])##===================================
            else:
                score, reason, judge_error = await score_llm_judge(##===================================
                    judge_model,
                    case["input"], case["expected"], result.output
                )
            if score >= PASS_THRESHOLD:
                passed += 1
            scores.append(score)
            result_id = eval_repo.add_result(##--------
                db, eval_run_id, case["id"], idx, result.output, score, reason,
                judge_error, result.latency_ms, result.tokens, result.run_id,
            )
            # Backfill trace linkage
            db.execute(
                "UPDATE agent_runs SET eval_result_id=? WHERE id=?",##========
                (result_id, result.run_id),
            )
            db.commit()##========


        total = len(cases)
        total_ms = int((time.monotonic() - started) * 1000)
        eval_repo.update_run_status(##--------
            db, eval_run_id, "completed",
            total=total, passed=passed,
            mean_score=round(sum(scores) / total, 4) if total else 0.0,
            pass_rate=round(passed / total, 4) if total else 0.0,
            total_ms=total_ms,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        eval_repo.update_run_status(db, eval_run_id, "failed", error=f"{type(exc).__name__}: {exc}"[:1000])##--------
        db.commit()
    finally:
        db.close()


def start_eval_run(tenant_id: str, eval_run_id: str) -> None:
    lock = _tenant_locks.setdefault(tenant_id, asyncio.Lock())

    async def _guarded():
        async with lock:
            await _run_eval(eval_run_id)##===================================
    asyncio.create_task(_guarded())

