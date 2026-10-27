"""Agent execution: SSE streaming for chat and one-shot runs for evaluation."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..repositories import threads as thread_repo##========
from ..util import message_text, sum_tokens, truncate
from . import trace_service##-------- ##===================================##===================================
from .agent_factory import AgentConfigError, build_agent
from .observability import build_langfuse_handler, extract_langfuse_ref ##===================================##===================================

logger = logging.getLogger(__name__)

# Portal-injected directive prefixes (skill/web-search) must not appear in titles.
_PREFIX_RE = re.compile(r"^\s*\[(?:技能：[^\]]+|联网搜索)\]\s*$", re.MULTILINE)
def _title_from_content(content: str) -> str:
    cleaned = _PREFIX_RE.sub("", content).strip()
    return truncate(cleaned or content, 30)

def _history_messages(db, thread_id: str):
    msgs = []
    for m in thread_repo.list_messages(db, thread_id):##========
        if m["role"] == "user":
            msgs.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant" and m["content"]:
            msgs.append(AIMessage(content=m["content"]))
    return msgs

def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": data}

async def run_stream(db, ctx, thread, agent: dict, content: str):
    """Yield SSE event dicts for one chat turn."""
    # Persist user message + open trace
    thread_repo.add_message(db, thread["id"], "user", content)##========
    thread_repo.touch_thread(db, thread["id"])##========
    if not thread["title"]:
        db.execute("UPDATE threads SET title=? WHERE id=?",
                     (_title_from_content(content), thread["id"]))##===================================
    run_id = trace_service.start(##--------
        db, tenant_id=ctx.tenant_id, agent_id=agent["id"], user_id=ctx.user_id or None,
        source="chat", content=content, thread_id=thread["id"],
    )
    db.commit()

    started = time.monotonic()
    try:
        compiled = build_agent(agent, thread["project_id"])##===================================##===================================
    except AgentConfigError as exc:
        latency = int((time.monotonic() - started) * 1000)
        trace_service.finish(db, run_id, status="failed", latency_ms=latency, error=str(exc))##--------
        db.commit()
        yield _sse("error", {"message": str(exc), "run_id": run_id})
        return




    handler = build_langfuse_handler(tags=["chat", f"tenant:{ctx.tenant_id}"])##返回langfuse回调##===================================
    callbacks = [handler] if handler else []
    config = {"callbacks": callbacks} if callbacks else {}

    history = _history_messages(db, thread["id"])##===================================
    inputs = {"messages": history[:-1] + [HumanMessage(content=content)]}

    seq = 0
    final_text = ""
    tokens = None
    # Immediate feedback: graph bootstrap + forced reasoning take a few
    # seconds before the first model delta arrives.
    yield _sse("thinking", {"text": ""})
    try:
        stream = compiled.astream(inputs, stream_mode=["messages", "updates"], config=config)
        async for mode, payload in stream:##===================================
            if mode == "messages":##===================================
                chunk, metadata = payload
                ns = (metadata or {}).get("langgraph_checkpoint_ns") or ""
                node = (metadata or {}).get("langgraph_node")
                # Top-level model node ns is "model:<task_id>"; subagent tokens
                # emitted inside the task tool nest deeper (":tools:<tid>:model:").
                nested = ns.count(":") > 1
                if nested or node != "model":
                    # Only stream top-level model tokens, not subagent chatter.
                    usage = getattr(chunk, "usage_metadata", None)
                    if usage:
                        tokens = sum_tokens(tokens, usage)
                    continue
                reasoning = (getattr(chunk, "additional_kwargs", None) or {}).get(
                    "reasoning_content"
                )
                if reasoning:
                    # Forced-thinking models (GLM-5.x) emit reasoning before
                    # content; forward it so the UI shows progress immediately.
                    yield _sse("thinking", {"text": reasoning})
                text = message_text(chunk.content)
                if text:
                    seq += 1
                    yield _sse("token", {"text": text})
                usage = getattr(chunk, "usage_metadata", None)
                if usage:
                    tokens = sum_tokens(tokens, usage)
            elif mode == "updates" and isinstance(payload, dict):##===================================
                for node, state_update in payload.items():
                    if not isinstance(state_update, dict) or "messages" not in state_update:
                        continue
                    for msg in state_update["messages"]:
                        if node == "model" and isinstance(msg, AIMessage):
                            if msg.tool_calls:
                                for tc in msg.tool_calls:
                                    seq += 1
                                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                                    trace_service.event(##--------
                                        db, run_id, seq, "tool_call", tc.get("name", ""),
                                        {"id": tc.get("id", ""), "args": args_str},
                                    )
                                    yield _sse("tool_call", {
                                        "id": tc.get("id", ""), "name": tc.get("name", ""),
                                        "args": truncate(args_str, 500),
                                    })
                            elif message_text(msg.content):
                                final_text = message_text(msg.content)
                                if msg.usage_metadata:
                                    tokens = sum_tokens(tokens, msg.usage_metadata)
                        elif node == "tools" and isinstance(msg, ToolMessage):
                            result_text = message_text(msg.content)
                            seq += 1
                            trace_service.event(##--------
                                db, run_id, seq, "tool_result", getattr(msg, "name", "") or "",
                                {"id": msg.tool_call_id, "content": truncate(result_text, 2000)},
                            )
                            yield _sse("tool_result", {
                                "id": msg.tool_call_id, "name": getattr(msg, "name", "") or "",
                                "content": truncate(result_text, 800),
                            })
        db.commit()
    except Exception as exc:  # noqa: BLE001 - surface via error event, persist failed run
        logger.exception("agent stream failed")
        latency = int((time.monotonic() - started) * 1000)
        err = f"{type(exc).__name__}: {exc}"
        trace_service.finish(db, run_id, status="failed", latency_ms=latency, error=err)##--------
        db.commit()
        yield _sse("error", {"message": "模型调用失败，请查看 trace 详情", "run_id": run_id})
        return

    if not final_text:
        # Fallback: model produced streamed text but no terminal AIMessage in updates
        final_text = "（模型未返回文本内容）"

    latency = int((time.monotonic() - started) * 1000)
    message_id = thread_repo.add_message(##========
        db, thread["id"], "assistant", final_text, tokens=tokens,
    )
    thread_repo.touch_thread(db, thread["id"])##========
    lf_id, lf_url = extract_langfuse_ref(handler) if handler else ("", "")##===================================
    trace_service.finish(##--------
        db, run_id, status="completed", output=final_text, latency_ms=latency,
        tokens=tokens, langfuse_trace_id=lf_id, langfuse_url=lf_url,
    )
    db.commit()
    yield _sse("done", {
        "message_id": message_id, "run_id": run_id, "content": final_text, "tokens": tokens,
        "langfuse_url": lf_url,
    })




def ________eval_service评估时用到(self):pass
@dataclass
class RunResult:
    output: str
    tokens: dict | None
    latency_ms: int
    run_id: str
    error: str = ""

async def run_agent_once(db, *, tenant_id: str, project_id: str,
                         agent: dict,
                         user_id: str | None, content: str, source: str = "evaluation", eval_run_id: str | None = None,
                         eval_result_id: str | None = None) -> RunResult:
    """Execute a single turn without streaming (used by evaluation)."""
    run_id = trace_service.start(##--------
        db, tenant_id=tenant_id, agent_id=agent["id"], user_id=user_id, source=source,
        content=content, eval_run_id=eval_run_id, eval_result_id=eval_result_id,
    )
    db.commit()
    started = time.monotonic()
    try:
        compiled = build_agent(agent, project_id)##===================================##===================================
    except AgentConfigError as exc:
        latency = int((time.monotonic() - started) * 1000)
        trace_service.finish(db, run_id, status="failed", latency_ms=latency, error=str(exc))##--------
        db.commit()
        return RunResult("", None, latency, run_id, str(exc))



    handler = build_langfuse_handler(tags=[source, f"tenant:{tenant_id}"])##返回langfuse回调##===================================
    config = {"callbacks": [handler]} if handler else {}
    seq = 0
    try:
        result = await compiled.ainvoke({"messages": [HumanMessage(content=content)]},
                                        config=config)
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        err = f"{type(exc).__name__}: {exc}"
        trace_service.finish(db, run_id, status="failed", latency_ms=latency, error=err)##--------
        db.commit()
        return RunResult("", None, latency, run_id, err)




    # Walk messages to record tool activity and find the final answer
    output = ""
    tokens = None
    for msg in result.get("messages", []):##===================================
        if isinstance(msg, AIMessage):
            if msg.usage_metadata:
                tokens = sum_tokens(tokens, msg.usage_metadata)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    seq += 1
                    trace_service.event(##--------
                        db, run_id, seq, "tool_call", tc.get("name", ""),
                        {"id": tc.get("id", ""), "args": json.dumps(tc.get("args", {}), ensure_ascii=False)},
                    )
            if message_text(msg.content) and not msg.tool_calls:
                output = message_text(msg.content)
        elif isinstance(msg, ToolMessage):
            seq += 1
            trace_service.event(##--------
                db, run_id, seq, "tool_result", getattr(msg, "name", "") or "",
                {"id": msg.tool_call_id, "content": truncate(message_text(msg.content), 2000)},
            )

    latency = int((time.monotonic() - started) * 1000)
    lf_id, lf_url = extract_langfuse_ref(handler) if handler else ("", "")##===================================
    trace_service.finish(##--------
        db, run_id, status="completed", output=output, latency_ms=latency,
        tokens=tokens, langfuse_trace_id=lf_id, langfuse_url=lf_url,
    )
    db.commit()
    return RunResult(output, tokens, latency, run_id)

