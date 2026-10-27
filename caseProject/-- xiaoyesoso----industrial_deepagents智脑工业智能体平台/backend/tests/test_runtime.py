"""DeepAgents runtime: SSE events, tool chain, FS isolation/deny, sandbox, failures."""
import json

from conftest import auth_headers, parse_sse, signup


def _make_agent(client, token, **overrides):
    payload = {"name": "测试专家", "tools": ["calculate", "current_datetime", "word_count"]}
    payload.update(overrides)
    resp = client.post("/api/agents", headers=auth_headers(token), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _new_thread(client, token, agent_id):
    resp = client.post("/api/threads", headers=auth_headers(token), json={"agent_id": agent_id})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _run(client, token, thread_id, content):
    resp = client.post(f"/api/threads/{thread_id}/runs",
                       headers=auth_headers(token), json={"content": content})
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)


def test_plain_chat_stream_and_persistence(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "你好")
    kinds = [e[0] for e in events]
    assert "done" in kinds
    done = [d for k, d in events if k == "done"][0]
    assert done["content"].startswith("REPLY:")
    assert done["tokens"]["total_tokens"] == 20
    assert done["run_id"]

    # Token streaming: top-level model chunks must surface as token events.
    # Regression guard for the ns filter ("model:<task_id>" is top-level).
    tokens = "".join(d["text"] for k, d in events if k == "token")
    assert tokens == done["content"]

    # Messages persisted (user + assistant)
    msgs = client.get(f"/api/threads/{tid}/messages", headers=auth_headers(token)).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_tool_chain_calculate(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "帮我算 123*456")
    by_kind = {}
    for kind, data in events:
        by_kind.setdefault(kind, []).append(data)

    calls = [e["name"] for e in by_kind.get("tool_call", [])]
    assert "calculate" in calls
    results = " ".join(e.get("content", "") for e in by_kind.get("tool_result", []))
    assert "56088" in results
    done = by_kind["done"][0]
    assert "FINAL_ANSWER" in done["content"]


def test_dangerous_arithmetic_rejected(client, fake_llm):
    # Direct unit test of the calculate tool safety guard
    from app.services.builtin_tools import calculate
    out = calculate.invoke({"expression": "__import__('os').system('ls')"})
    assert out.startswith("ERROR")


def test_harness_filesystem_tools_available(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "please write a file named hello")
    calls = [d["name"] for k, d in events if k == "tool_call"]
    assert "write_file" in calls
    results = [d.get("content", "") for k, d in events if k == "tool_result"]
    assert results, "write_file should return a tool result"


def test_env_file_read_denied(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "read .env now")
    results = [d.get("content", "").lower() for k, d in events if k == "tool_result"]
    assert results, "expected a tool result for the denied read"
    joined = " ".join(results)
    assert "test-api-key" not in joined
    assert any(word in joined for word in ("den", "forbidden", "not allowed", "permission", "拒绝"))


def test_sandbox_execute_tool_and_scrubbed_env(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token, name="沙箱专家", sandbox_enabled=True)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "run python please")
    calls = [d["name"] for k, d in events if k == "tool_call"]
    assert "execute" in calls
    results = " ".join(d.get("content", "") for k, d in events if k == "tool_result")
    assert "2" in results

    # Second turn: env must not carry the host API_KEY
    tid2 = _new_thread(client, token, agent["id"])
    events2 = _run(client, token, tid2, "show env vars now")
    env_out = " ".join(d.get("content", "") for k, d in events2 if k == "tool_result")
    assert "API_KEY" not in env_out
    assert "test-api-key" not in env_out


def test_sandbox_disabled_hides_execute(client, fake_llm):
    token, _ = signup(client)
    # tools=["calculate"]; sandbox disabled -> fs tools present, execute absent
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])
    # A model turn is required: deepagents binds tools at runtime, not compile time
    _run(client, token, tid, "hello, please reply plainly")
    assert "execute" not in fake_llm.tool_names
    assert "write_file" in fake_llm.tool_names
    assert "calculate" in fake_llm.tool_names


def test_planning_middleware_write_todos(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token, name="规划专家", planning_enabled=True)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "please make a plan for this")
    calls = [d["name"] for k, d in events if k == "tool_call"]
    assert "write_todos" in calls


def test_history_continuation(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    _run(client, token, tid, "第一句话")
    _run(client, token, tid, "第二句话")
    msgs = client.get(f"/api/threads/{tid}/messages", headers=auth_headers(token)).json()
    assert len(msgs) == 4


def test_failed_run_persisted_and_error_event(client, monkeypatch):
    from app.services import agent_factory
    from conftest import FailingChatModel

    monkeypatch.setattr(agent_factory, "build_chat_model",
                        lambda settings=None, model_name="": FailingChatModel())
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    events = _run(client, token, tid, "触发失败")
    kinds = [k for k, _ in events]
    assert "error" in kinds
    done = client.get("/api/threads", headers=auth_headers(token)).json()

    # Trace is persisted as failed with masked secret
    traces = client.get("/api/traces", headers=auth_headers(token)).json()
    failed = [t for t in traces if t["status"] == "failed"]
    assert failed
    assert "FakeKeyForMaskTests" not in failed[0]["error"]
    assert "****" in failed[0]["error"]
