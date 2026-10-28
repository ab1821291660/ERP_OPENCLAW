"""Evaluation: scorer unit tests plus end-to-end eval runs via the API."""
import asyncio
import time

from conftest import FakeJudge, FailingJudge, auth_headers, signup
from app.services.eval_service import (
    parse_judge_json,
    score_contains,
    score_exact,
    score_llm_judge,
)


# ---------- scorer unit tests ----------

def test_score_contains_all_keywords_and_logic():
    assert score_contains("Hello World", "hello|world") == (1.0, "all keywords found")
    score, reason = score_contains("hello", "hello|missing")
    assert score == 0.0 and "missing" in reason
    # case-insensitive and whitespace tolerant
    assert score_contains("  REPLY: hi  ", "reply") == (1.0, "all keywords found")
    score, _ = score_contains("anything", "")
    assert score == 0.0


def test_score_exact_normalization():
    assert score_exact("Hello   World", "hello world")[0] == 1.0
    assert score_exact("Hello World", "hello  world!")[0] == 0.0


def test_parse_judge_json_variants():
    assert parse_judge_json('{"score": 0.8, "reason": "ok"}') == (0.8, "ok")
    # JSON embedded in prose
    score, _ = parse_judge_json('Here is my verdict:\n{"score": 0.5, "reason": "partial"}\n')
    assert score == 0.5
    # scores are clamped to [0, 1]
    assert parse_judge_json('{"score": 3.5}')[0] == 1.0
    assert parse_judge_json('{"score": -2}')[0] == 0.0


def test_llm_judge_success_and_failure_isolation():
    score, reason, err = asyncio.run(
        score_llm_judge(FakeJudge(), "q", "a", "real output")
    )
    assert score == 1.0 and reason == "correct" and err == ""

    # A broken judge must never raise; the case simply scores 0 with an error note
    score, _, err = asyncio.run(
        score_llm_judge(FailingJudge(), "q", "a", "real output")
    )
    assert score == 0.0 and "judge boom" in err

    # Empty agent output short-circuits without calling the model
    score, _, err = asyncio.run(score_llm_judge(FakeJudge(), "q", "a", ""))
    assert score == 0.0 and err == "empty agent output"


# ---------- API helpers ----------

def _make_agent(client, token, **overrides):
    payload = {"name": "评测专家", "tools": ["calculate"]}
    payload.update(overrides)
    resp = client.post("/api/agents", headers=auth_headers(token), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_dataset(client, token, name="基础集", cases=None):
    resp = client.post("/api/eval/datasets", headers=auth_headers(token),
                       json={"name": name, "description": "d"})
    assert resp.status_code == 201, resp.text
    did = resp.json()["id"]
    for text_input, expected in cases or []:
        r = client.post(f"/api/eval/datasets/{did}/cases",
                        headers=auth_headers(token),
                        json={"input": text_input, "expected": expected})
        assert r.status_code == 201, r.text
    return did


def _start_run(client, token, dataset_id, agent_id, judge="contains"):
    resp = client.post("/api/eval/runs", headers=auth_headers(token),
                       json={"dataset_id": dataset_id, "agent_id": agent_id, "judge": judge})
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def _wait_run(client, token, run_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/eval/runs/{run_id}", headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.1)
    raise AssertionError("eval run did not finish in time")


# ---------- dataset / case API ----------

def test_dataset_crud_and_case_count(client, fake_llm):
    token, _ = signup(client)
    did = _make_dataset(client, token, cases=[("问题1", "answer1"), ("问题2", "answer2")])

    listing = client.get("/api/eval/datasets", headers=auth_headers(token)).json()
    match = [d for d in listing if d["id"] == did][0]
    assert match["case_count"] == 2

    cases = client.get(f"/api/eval/datasets/{did}", headers=auth_headers(token)).json()
    assert [c["input"] for c in cases] == ["问题1", "问题2"]

    # Empty dataset cannot be evaluated
    empty_did = _make_dataset(client, token, name="空集")
    agent = _make_agent(client, token)
    resp = client.post("/api/eval/runs", headers=auth_headers(token),
                       json={"dataset_id": empty_did, "agent_id": agent["id"], "judge": "contains"})
    assert resp.status_code == 400

    # Invalid judge type is rejected at the schema layer
    resp = client.post("/api/eval/runs", headers=auth_headers(token),
                       json={"dataset_id": did, "agent_id": agent["id"], "judge": "bogus"})
    assert resp.status_code == 422


# ---------- contains run, end to end ----------

def test_contains_eval_run_scoring_and_trace_link(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    # Fake model replies "REPLY: <input>" -> case 1 passes, case 2 misses keyword
    did = _make_dataset(client, token, cases=[
        ("greetme", "reply"),
        ("otherone", "keyword-that-never-appears"),
    ])
    run_id = _start_run(client, token, did, agent["id"], judge="contains")
    body = _wait_run(client, token, run_id)

    assert body["status"] == "completed"
    assert body["total"] == 2 and body["passed"] == 1
    assert body["pass_rate"] == 0.5 and body["mean_score"] == 0.5
    assert body["total_ms"] >= 0
    assert len(body["results"]) == 2
    # results are sorted by score ascending: failing case first
    assert body["results"][0]["score"] == 0.0
    assert "missing" in body["results"][0]["judge_reason"]
    assert body["results"][1]["score"] == 1.0

    # Every result is linked to a trace run of source=evaluation
    for result in body["results"]:
        trace_id = result["trace_run_id"]
        assert trace_id
        tr = client.get(f"/api/traces/{trace_id}", headers=auth_headers(token))
        assert tr.status_code == 200, tr.text
        trace = tr.json()
        assert trace["source"] == "evaluation"
        assert trace["status"] == "completed"

    # The run also appears in the run list
    runs = client.get("/api/eval/runs", headers=auth_headers(token)).json()
    assert any(r["id"] == run_id and r["status"] == "completed" for r in runs)


def test_exact_eval_run_normalized_match(client, fake_llm):
    token, _ = signup(client)
    agent = _make_agent(client, token)
    # Fake output is "REPLY: exactmatch"; expected differs only by case/whitespace
    did = _make_dataset(client, token, cases=[("exactmatch", "REPLY:  exactmatch")])
    run_id = _start_run(client, token, did, agent["id"], judge="exact")
    body = _wait_run(client, token, run_id)
    assert body["status"] == "completed"
    assert body["passed"] == 1 and body["results"][0]["score"] == 1.0


# ---------- llm judge ----------

def test_llm_judge_eval_run(client, fake_llm, monkeypatch):
    from app.services import eval_service
    monkeypatch.setattr(eval_service, "build_judge_model", lambda: FakeJudge())

    token, _ = signup(client)
    agent = _make_agent(client, token)
    did = _make_dataset(client, token, cases=[("anything", "whatever")])
    run_id = _start_run(client, token, did, agent["id"], judge="llm_judge")
    body = _wait_run(client, token, run_id)

    assert body["status"] == "completed"
    assert body["passed"] == 1
    result = body["results"][0]
    assert result["score"] == 1.0 and result["judge_reason"] == "correct"
    assert result["judge_error"] in (None, "")


def test_llm_judge_failure_does_not_abort_run(client, fake_llm, monkeypatch):
    from app.services import eval_service
    monkeypatch.setattr(eval_service, "build_judge_model", lambda: FailingJudge())

    token, _ = signup(client)
    agent = _make_agent(client, token)
    did = _make_dataset(client, token, cases=[("q1", "a1"), ("q2", "a2")])
    run_id = _start_run(client, token, did, agent["id"], judge="llm_judge")
    body = _wait_run(client, token, run_id)

    assert body["status"] == "completed"
    assert body["total"] == 2
    assert all(r["score"] == 0.0 and "judge boom" in (r["judge_error"] or "")
               for r in body["results"])


# ---------- failures and isolation ----------

def test_eval_run_fails_when_agent_missing(client, fake_llm):
    token, me = signup(client)
    did = _make_dataset(client, token, cases=[("q", "a")])
    agent = _make_agent(client, token)

    # Create a run row, then remove the agent (FK enforcement is connection-scoped)
    from app.db import connect
    from app.repositories import evals as eval_repo
    db = connect()
    # PRAGMA foreign_keys cannot be changed inside a transaction
    db.execute("PRAGMA foreign_keys=OFF")
    run_id = eval_repo.create_run(db, me["user"]["tenant_id"], did,
                                  agent["id"], "contains", 1)
    db.execute("DELETE FROM agents WHERE id=?", (agent["id"],))
    db.commit()
    db.close()

    from app.services.eval_service import _run_eval
    asyncio.run(_run_eval(run_id))

    db = connect()
    row = eval_repo.get_run(db, run_id, me["user"]["tenant_id"])
    assert row["status"] == "failed"
    assert "agent not found" in (row["error"] or "")


def test_eval_runs_are_tenant_isolated(client, fake_llm):
    token_a, _ = signup(client, email="alice@example.com", org="Acme")
    token_b, _ = signup(client, email="bob@example.com", org="Other")

    agent_a = _make_agent(client, token_a)
    did_a = _make_dataset(client, token_a, cases=[("hello", "reply")])
    run_a = _start_run(client, token_a, did_a, agent_a["id"])
    _wait_run(client, token_a, run_a)

    # Bob cannot see Alice's dataset, run, or the linked traces
    assert client.get(f"/api/eval/datasets/{did_a}",
                      headers=auth_headers(token_b)).status_code == 404
    assert client.get(f"/api/eval/runs/{run_a}",
                      headers=auth_headers(token_b)).status_code == 404
    run_body = client.get(f"/api/eval/runs/{run_a}",
                          headers=auth_headers(token_a)).json()
    trace_id = run_body["results"][0]["trace_run_id"]
    assert client.get(f"/api/traces/{trace_id}",
                      headers=auth_headers(token_b)).status_code == 404

    # Bob's run list does not contain Alice's run
    bob_runs = client.get("/api/eval/runs", headers=auth_headers(token_b)).json()
    assert all(r["id"] != run_a for r in bob_runs)
