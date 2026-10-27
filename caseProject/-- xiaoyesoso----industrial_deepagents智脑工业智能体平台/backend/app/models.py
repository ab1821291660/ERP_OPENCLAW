"""Pydantic request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

# ---------- auth ----------
class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    org_name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: str
    password: str


class TenantOut(BaseModel):
    id: str
    name: str
    role: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    tenant_id: str
    tenant_name: str
    role: str


class AuthOut(BaseModel):
    token: str
    user: UserOut
    tenants: list[TenantOut] = []


# ---------- tenants / members / keys ----------
class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SwitchIn(BaseModel):
    tenant_id: str


class MemberIn(BaseModel):
    email: str
    role: str = Field(pattern="^(admin|member|viewer)$")


class MemberUpdateIn(BaseModel):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: str
    created_at: str


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: str | None = None
    plaintext: str | None = None


# ---------- agents ----------
class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    tools: list[str] = []
    sandbox_enabled: bool = False
    planning_enabled: bool = False


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str
    model: str
    tools: list[str]
    sandbox_enabled: bool
    planning_enabled: bool
    project_id: str
    created_at: str
    updated_at: str


# ---------- threads / runs ----------
class ThreadIn(BaseModel):
    agent_id: str
    title: str = ""
    project_id: str = ""


class RunIn(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    tool_calls: list | None = None
    tokens: dict | None = None
    created_at: str


class ThreadOut(BaseModel):
    id: str
    agent_id: str
    agent_name: str = ""
    project_id: str = ""
    title: str
    created_at: str
    updated_at: str


class ProjectOut(BaseModel):
    id: str
    name: str
    slug: str = ""
    created_at: str
    thread_count: int = 0


class ProjectIn(BaseModel):
    name: str = Field(default="", max_length=80)


# ---------- evaluation ----------
class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""


class CaseIn(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)
    expected: str = Field(default="", max_length=20_000)


class CaseOut(BaseModel):
    id: str
    input: str
    expected: str


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    case_count: int = 0
    created_at: str


class EvalRunIn(BaseModel):
    dataset_id: str
    agent_id: str
    judge: str = Field(pattern="^(contains|exact|llm_judge)$")


class EvalRunOut(BaseModel):
    id: str
    dataset_id: str
    agent_id: str
    judge: str
    status: str
    total: int
    passed: int
    mean_score: float
    pass_rate: float
    total_ms: int
    error: str
    created_at: str
    completed_at: str | None = None
    results: list[dict] | None = None
