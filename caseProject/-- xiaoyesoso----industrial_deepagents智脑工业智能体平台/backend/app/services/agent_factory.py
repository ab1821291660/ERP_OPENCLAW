"""Build and cache compiled deepagents, one per (agent config x project)."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
from langchain_openai import ChatOpenAI
from langchain.agents.middleware.todo import TodoListMiddleware
from typing import Any

from ..config import Settings, get_settings
from .builtin_tools import PLATFORM_TOOL_MAP


class ReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI that preserves provider reasoning deltas (e.g. Zhipu GLM).

    GLM-5.x streams chain-of-thought as ``delta.reasoning_content`` while
    ``delta.content`` stays empty. langchain-openai drops that field, so during
    the (forced) thinking window the client receives zero bytes. We stash the
    reasoning text on ``additional_kwargs["reasoning_content"]`` so the
    streaming layer can forward it as a separate "thinking" event.
    """

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        gen = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        try:
            choices = chunk.get("choices") or []
            delta: dict[str, Any] = (choices[0].get("delta") or {}) if choices else {}
            reasoning = delta.get("reasoning_content")
        except (AttributeError, IndexError):
            reasoning = None
        if gen is not None and reasoning:
            gen.message.additional_kwargs["reasoning_content"] = reasoning
        return gen

# Paths the agent must never read/write through the virtual filesystem.
# deepagents permission patterns are absolute virtual paths (must start with "/").
_DENY_PATTERNS = [
    "/.env", "/.env.*", "/**/.env", "/**/.env.*",
    "/**/*.key", "/**/credentials*", "/**/.ssh/**", "/**/id_rsa*",
]
def ________kv(self):pass
_cache: dict[str, object] = {}
_cache_lock = threading.Lock()

# Platform-level deepagents skills library (see deepagents SkillsMiddleware):
# each subdirectory carries a SKILL.md; agents load only name/description at
# startup (progressive disclosure) and read the full file when a task matches.
SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
def _skills_fingerprint() -> str:
    """Cheap change-detector for the skills library (max mtime over files)."""
    if not SKILLS_DIR.is_dir():
        return "none"
    try:
        newest = max(f.stat().st_mtime for f in SKILLS_DIR.rglob("*") if f.is_file())
        return str(newest)
    except OSError:
        return "none"


def project_fs_root(tenant_id: str, project_id: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    root = settings.fs_root / tenant_id / project_id
    root.mkdir(parents=True, exist_ok=True)
    return root
def build_chat_model(settings: Settings | None = None, model_name: str = ""):
    """Construct the OpenAI-compatible chat model (Zhipu GLM). Overridable in tests."""
    settings = settings or get_settings()
    if not settings.api_key:
        raise AgentConfigError("LLM API_KEY is not configured on the server.")
    return ReasoningChatOpenAI(
        model=model_name or settings.llm_model,
        api_key=settings.api_key,
        base_url=settings.base_url.rstrip("/"),
        temperature=0.3,
        timeout=90,
        max_retries=2,
    )


def build_judge_model(settings: Settings | None = None):
    settings = settings or get_settings()
    if not settings.api_key:
        raise AgentConfigError("LLM API_KEY is not configured on the server.")
    return ChatOpenAI(
        model=settings.flash_llm_model,
        api_key=settings.api_key,
        base_url=settings.base_url.rstrip("/"),
        temperature=0.0,
        timeout=60,
        max_retries=1,
    )


class AgentConfigError(RuntimeError):
    pass







def ________(self):pass
def _cache_key(agent: dict, project_id: str) -> str:
    return "|".join([
        agent["id"], project_id, agent["updated_at"],
        str(int(agent.get("sandbox_enabled", False))),
        str(int(agent.get("planning_enabled", False))),
        ",".join(sorted(agent.get("tools", []))),
        agent.get("model", ""),
        _skills_fingerprint(),
    ])

def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()##========

def build_agent(agent: dict, project_id: str, *, model=None, settings: Settings | None = None):
    """Compile (or fetch cached) deep agent for the given agent row + project."""
    settings = settings or get_settings()
    key = _cache_key(agent, project_id)##========
    with _cache_lock:
        cached = _cache.get(key)##========
        if cached is not None:
            return cached



    chat = model or build_chat_model(settings, agent.get("model", ""))##===================================
    root = project_fs_root(agent["tenant_id"], project_id, settings)##===================================
    skills: None = None
    if agent.get("sandbox_enabled"):
        # deepagents LocalShellBackend: cwd=root, virtual overlay, scrubbed env,
        # timeout and output cap. NOTE: filesystem permissions are not supported
        # together with execution backends (framework raises NotImplementedError).
        # Sandbox backends cannot host the platform skills route (virtual overlay),
        # so sandbox agents run without platform skills in this iteration.
        backend = LocalShellBackend(
            root_dir=str(root),##===================================##===================================
            virtual_mode=True,
            timeout=settings.sandbox_timeout,##60
            max_output_bytes=settings.sandbox_max_output,##20000
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
                "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                "HOME": str(root),
            },
            inherit_env=False,
        )
        permissions = None
    else:##非沙箱----
        project_backend = FilesystemBackend(root_dir=str(root))##===================================##===================================
        permissions = [
            FilesystemPermission(operations=["read", "write"],
                                 paths=_DENY_PATTERNS,
                                 mode="deny"),
        ]
        # Mount the platform skills library under the virtual /skills/ prefix:
        # FilesystemBackend defaults to virtual_mode=True, so absolute-path
        # sources are rejected; routing a second backend via CompositeBackend
        # keeps the library shared across projects without copying files.
        if SKILLS_DIR.is_dir():
            backend = CompositeBackend(##===================================##===================================
                default=project_backend,##===================================##===================================
                routes={"/skills/": FilesystemBackend(root_dir=str(SKILLS_DIR))},##===================================##===================================
            )
            # Agents may read skill files but must not mutate the shared library.
            permissions.append(FilesystemPermission(operations=["write"],
                                                    paths=["/skills/**"],
                                                    mode="deny"))
            skills = ["/skills/"]
        else:
            backend = project_backend

    tools = [PLATFORM_TOOL_MAP[name] for name in agent.get("tools", []) if name in PLATFORM_TOOL_MAP]
    middleware = [TodoListMiddleware()] if agent.get("planning_enabled") else ()##===================================



    compiled = create_deep_agent(
        model=chat,
        tools=tools,

        system_prompt=agent.get("system_prompt") or "You are a helpful assistant.",
        backend=backend,
        permissions=permissions,
        middleware=middleware,

        skills=skills,
        name=f"agent_{agent['id'].replace('-', '')[:16]}",
    )
    with _cache_lock:
        _cache_cache(key, compiled)##========
    return compiled
def _cache_cache(key: str, value) -> None:
    _cache[key] = value##========

