"""Pytest fixtures: isolated data dir, test client, scripted fake chat model."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict


@pytest.fixture
def platform_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("API_KEY", "test-api-key-0000")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)

    from app.config import get_settings
    get_settings.cache_clear()

    from app.db import _initialized
    _initialized.clear()

    from app.services.agent_factory import clear_cache
    clear_cache()

    from app.db import init_db
    init_db()
    yield tmp_path


@pytest.fixture
def client(platform_env):
    from app.main import app
    with TestClient(app) as c:
        yield c


class FakeChatModel(BaseChatModel):
    """Scripted chat model: emits tool calls on trigger phrases, then finalizes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    bound_tools: list = []
    tool_names: set = set()
    final_usage: dict | None = None

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        self.tool_names = {getattr(t, "name", str(t)) for t in tools}
        return self

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _pick_response(self, messages) -> AIMessage:
        last_user = ""
        saw_tool_result = False
        tool_text = ""
        for m in messages:
            if isinstance(m, HumanMessage):
                last_user = m.content if isinstance(m.content, str) else str(m.content)
            elif isinstance(m, ToolMessage):
                saw_tool_result = True
                tool_text = m.content if isinstance(m.content, str) else str(m.content)

        if saw_tool_result:
            return AIMessage(content=f"FINAL_ANSWER based on tool result: {tool_text[:200]}",
                             usage_metadata=self.final_usage)

        if "123*456" in last_user and "calculate" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "calculate", "args": {"expression": "123*456"}, "id": "tc_calc"}])
        if "read .env" in last_user and "read_file" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "read_file", "args": {"file_path": ".env"}, "id": "tc_env"}])
        if "write a file" in last_user and "write_file" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"file_path": "hello.txt", "content": "hi from agent"},
                "id": "tc_write"}])
        if "run python" in last_user and "execute" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "execute", "args": {"command": "python3 -c \"print(1+1)\""}, "id": "tc_exec"}])
        if "show env" in last_user and "execute" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "execute", "args": {"command": "env"}, "id": "tc_env2"}])
        if "make a plan" in last_user and "write_todos" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "write_todos", "args": {"todos": [{"content": "step 1", "status": "in_progress"}]},
                "id": "tc_todo"}])
        return AIMessage(content=f"REPLY: {last_user[:80]}", usage_metadata=self.final_usage)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._pick_response(list(messages)))])


class FailingChatModel(BaseChatModel):
    """Chat model whose every call raises (upstream failure)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "failing"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("upstream 500 with token 00000000000000000000000000000000.FakeKeyForMaskTests")


class FakeJudge:
    """Minimal judge model returning a fixed JSON verdict."""

    def __init__(self, verdict: str = '{"score": 1.0, "reason": "correct"}'):
        self.verdict = verdict

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content=self.verdict)


class FailingJudge:
    async def ainvoke(self, messages, **kwargs):
        raise RuntimeError("judge boom")


@pytest.fixture
def fake_llm(monkeypatch):
    from app.services import agent_factory

    fake = FakeChatModel(final_usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20})

    def _fake_chat(settings=None, model_name=""):
        return fake

    def _fake_judge(settings=None):
        return fake

    monkeypatch.setattr(agent_factory, "build_chat_model", _fake_chat)
    monkeypatch.setattr(agent_factory, "build_judge_model", _fake_judge)
    return fake


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if name:
            events.append((name, data))
    return events


def signup(client, email="alice@example.com", password="secret123", name="Alice", org="Acme"):
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": password, "display_name": name, "org_name": org,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["token"], body


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
