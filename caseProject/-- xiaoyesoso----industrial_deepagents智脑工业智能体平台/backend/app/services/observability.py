"""Optional Langfuse integration (v4 SDK, OpenTelemetry-based CallbackHandler)."""
from __future__ import annotations

import os

from ..config import Settings, get_settings


def build_langfuse_handler(settings: Settings | None = None, tags: list[str] | None = None):
    """Return a Langfuse CallbackHandler when LANGFUSE_* is configured, else None.

    The v4 handler reads secret/host from environment variables; we mirror the
    .env-derived settings into os.environ so explicit configuration also works.
    """
    settings = settings or get_settings()
    if not settings.langfuse_enabled:
        return None
    try:
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
        if tags:
            # Tags/session are normally passed per-run via config metadata in v4;
            # kept here for forward compatibility.
            setattr(handler, "_platform_tags", tags)
        return handler
    except Exception:  # noqa: BLE001 - tracing must never break agent runs
        return None


def extract_langfuse_ref(handler) -> tuple[str, str]:
    """Best-effort extraction of (trace_id, url) after a run completed."""
    settings = get_settings()
    trace_id = getattr(handler, "trace_id", "") or ""
    url = f"{settings.langfuse_host.rstrip('/')}/traces/{trace_id}" if trace_id else ""
    return trace_id, url
