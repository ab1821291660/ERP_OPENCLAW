"""Small shared helpers."""
from __future__ import annotations

import re
import uuid
from collections import Counter


def new_id() -> str:
    return uuid.uuid4().hex


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or f"org-{uuid.uuid4().hex[:8]}"


def unique_slug(base: str, exists) -> str:
    """Return a slug not yet taken; `exists(slug) -> bool`."""
    candidate = base
    n = 2
    while exists(candidate):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


# Tokens that must never land in persisted traces / error messages
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(?i)(authorization\s*[=:]\s*bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]{16,})"),
    # Zhipu keys look like 32hex.alphanum
    re.compile(r"\b([0-9a-f]{24,64})\.([A-Za-z0-9]{8,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9]{12,})\b"),
]


def sanitize(text: str | None) -> str:
    """Mask secrets in arbitrary text before persistence / display."""
    if not text:
        return ""
    out = text
    for pat in _SECRET_PATTERNS:
        def _mask(m: re.Match) -> str:
            if len(m.groups()) == 2 and m.group(1):
                return m.group(1) + "****"
            return "****"
        out = pat.sub(_mask, out)
    return out


def message_text(content) -> str:
    """Normalize LangChain message content (str | content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return str(content or "")


def sum_tokens(acc: dict | None, usage: dict | None) -> dict:
    """Accumulate usage_metadata dictionaries, taking input tokens once."""
    base = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if acc:
        base.update({k: v for k, v in acc.items() if k in base})
    if usage:
        # Only count prompt/input side once: take the max across chunks.
        base["input_tokens"] = max(base["input_tokens"], int(usage.get("input_tokens", 0)))
        base["output_tokens"] = max(base["output_tokens"], int(usage.get("output_tokens", 0)))
        total = int(usage.get("total_tokens", 0))
        base["total_tokens"] = max(base["total_tokens"], total)
    if not base["total_tokens"]:
        base["total_tokens"] = base["input_tokens"] + base["output_tokens"]
    return base


def top_words(text: str, limit: int = 10) -> dict:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    return dict(Counter(words).most_common(limit))
