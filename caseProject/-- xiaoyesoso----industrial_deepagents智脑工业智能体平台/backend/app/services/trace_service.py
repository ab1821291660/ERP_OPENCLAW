"""Trace orchestration: start/event/finish with truncation and secret masking."""
from __future__ import annotations

from ..repositories import traces as repo
from ..util import sanitize, truncate

INPUT_LIMIT = 2000
OUTPUT_LIMIT = 4000
EVENT_LIMIT = 4000


def start(db, *, tenant_id, agent_id, user_id, source, content,
          thread_id=None, eval_run_id=None, eval_result_id=None) -> str:
    return repo.start_run(
        db, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id, source=source,
        input_preview=sanitize(truncate(content, INPUT_LIMIT)),
        thread_id=thread_id, eval_run_id=eval_run_id, eval_result_id=eval_result_id,
    )


def event(db, run_id: str, seq: int, event_type: str, name: str = "", data: dict | None = None):
    safe = {}
    for k, v in (data or {}).items():
        if isinstance(v, str):
            safe[k] = sanitize(truncate(v, EVENT_LIMIT))
        else:
            safe[k] = v
    repo.add_event(db, run_id, seq, event_type, name, safe)


def finish(db, run_id: str, *, status: str, output: str = "", latency_ms: int = 0,
           tokens: dict | None = None, error: str = "", langfuse_trace_id: str = "",
           langfuse_url: str = ""):
    repo.finish_run(
        db, run_id, status=status,
        output_preview=sanitize(truncate(output, OUTPUT_LIMIT)),
        latency_ms=latency_ms, tokens=tokens, error=sanitize(error)[:2000],
        langfuse_trace_id=langfuse_trace_id, langfuse_url=langfuse_url,
    )
