"""Observability: trace listing/filtering, detail with events, stats, redaction."""
from conftest import (
    FailingChatModel,
    auth_headers,
    parse_sse,
    signup,
)


def _make_agent(client, token, **overrides):
    payload = {"name": "追踪专家", "tools": ["calculate"]}
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


def _run_id(events):
    return [d for k, d in events if k == "done"][0]["run_id"]


def test_trace_list_filters_and_detail_with_events(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])

    # A tool-using turn: tool_call + tool_result must be recorded as events
    events = _run(client, token, tid, "帮我算 123*456")
    run_id = _run_id(events)

    # Default list contains the run
    rows = client.get("/api/traces", headers=auth_headers(token)).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == run_id
    assert row["status"] == "completed"
    assert row["source"] == "chat"
    assert row["agent_id"] == agent["id"]
    assert row["agent_name"] == "追踪专家"
    assert row["tokens"]["total_tokens"] == 20
    assert row["langfuse_url"] in (None, "")
    assert "56088" in row["output_preview"]

    # Query filters
    assert client.get("/api/traces?status=failed",
                      headers=auth_headers(token)).json() == []
    assert len(client.get(f"/api/traces?agent_id={agent['id']}",
                          headers=auth_headers(token)).json()) == 1
    assert len(client.get(f"/api/traces?thread_id={tid}",
                          headers=auth_headers(token)).json()) == 1
    assert client.get("/api/traces?thread_id=bogus",
                      headers=auth_headers(token)).json() == []

    # Detail view carries ordered events
    detail = client.get(f"/api/traces/{run_id}", headers=auth_headers(token))
    assert detail.status_code == 200
    body = detail.json()
    kinds = [e["type"] for e in body["events"]]
    assert "tool_call" in kinds and "tool_result" in kinds
    calc_event = [e for e in body["events"] if e["type"] == "tool_call"][0]
    assert calc_event["name"] == "calculate"

    # Unknown run -> 404
    assert client.get("/api/traces/bogus-id",
                      headers=auth_headers(token)).status_code == 404

    # limit out of range -> 422
    assert client.get("/api/traces?limit=999",
                      headers=auth_headers(token)).status_code == 422


def test_trace_stats_24h(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])
    _run(client, token, tid, "你好")

    stats = client.get("/api/observability/stats", headers=auth_headers(token)).json()
    assert stats["runs"] == 1
    assert stats["success_rate"] == 1.0
    assert stats["avg_latency_ms"] >= 0
    assert stats["avg_tokens"] == 20


def test_failed_run_is_traced_and_secret_redacted(client, monkeypatch):
    from app.services import agent_factory
    monkeypatch.setattr(agent_factory, "build_chat_model",
                        lambda settings=None, model_name="": FailingChatModel())

    token, _ = signup(client)
    agent = _make_agent(client, token)
    tid = _new_thread(client, token, agent["id"])
    events = _run(client, token, tid, "随便说点什么")

    error_events = [d for k, d in events if k == "error"]
    assert error_events and error_events[0]["run_id"]
    run_id = error_events[0]["run_id"]

    rows = client.get("/api/traces?status=failed",
                      headers=auth_headers(token)).json()
    assert len(rows) == 1 and rows[0]["status"] == "failed"

    detail = client.get(f"/api/traces/{run_id}", headers=auth_headers(token)).json()
    # The upstream error embeds a zhipu-style key; it must never be stored verbatim
    assert "00000000000000000000000000000000.FakeKeyForMaskTests" not in detail["error"]
    assert "****" in detail["error"]


def test_traces_require_auth_and_tenant_isolation(client, fake_llm):
    assert client.get("/api/traces").status_code == 401
    assert client.get("/api/observability/stats").status_code == 401

    token_a, _ = signup(client, email="alice@example.com", org="Acme")
    agent = _make_agent(client, token_a)
    tid = _new_thread(client, token_a, agent["id"])
    run_id = _run_id(_run(client, token_a, tid, "你好"))

    token_b, _ = signup(client, email="bob@example.com", org="Other")
    assert client.get(f"/api/traces/{run_id}",
                      headers=auth_headers(token_b)).status_code == 404
    bob_rows = client.get("/api/traces", headers=auth_headers(token_b)).json()
    assert all(r["id"] != run_id for r in bob_rows)
    stats_b = client.get("/api/observability/stats",
                         headers=auth_headers(token_b)).json()
    assert stats_b["runs"] == 0
