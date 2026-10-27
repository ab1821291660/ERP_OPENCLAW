"""Stage 20 — Transient Retry / Backoff.

Wrap LLM calls in a small retry loop that fires only on *transient*
provider errors (overloaded, 429, 529, rate limit, timeout).
Deterministic errors (auth, not-found, validation) bypass the retry
and propagate immediately so they don't masquerade as flakes.

Run::

    uv run python stages_c/stage_20_transient_retry_backoff.py
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

# ── The transient-error allowlist ─────────────────────────────────────────
#
# Substrings that match the human-readable messages of the provider
# exceptions worth retrying.  Lower-cased before comparison.

TRANSIENT_SUBSTRINGS: tuple[str, ...] = (
    "overloaded_error",
    "overloaded",
    "rate limit",
    "rate_limit",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "429",
    "529",
)


def is_transient_model_error(message: str) -> bool:
    """Return True if ``message`` looks like a transient provider error."""
    lowered = message.lower()
    return any(needle in lowered for needle in TRANSIENT_SUBSTRINGS)


# ── The retry wrapper ─────────────────────────────────────────────────────


T = TypeVar("T")


def retry_on_transient(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``fn``; retry only on transient errors with linear backoff.

    Backoff is ``base_delay_s * (attempt + 1)`` — a deliberately simple
    schedule.  Exponential is fine too; the lesson is the predicate, not
    the curve.

    Args:
        fn: The zero-arg callable to execute.  Wrap your real LLM call
            in a closure or ``functools.partial`` to fit this signature.
        max_attempts: Total tries before giving up (counts the first
            call).  Must be at least 1.
        base_delay_s: Seconds for the first backoff; subsequent backoffs
            scale linearly with attempt number.
        sleep: Injected so tests can run without wall-clock waits.

    Returns:
        Whatever ``fn`` returns once it succeeds.

    Raises:
        Exception: re-raises the underlying exception if it's not
            transient, or after ``max_attempts`` transient failures.
    """
    if max_attempts < 1:
        msg = "max_attempts must be >= 1"
        raise ValueError(msg)

    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            last_attempt = attempt == max_attempts - 1
            if last_attempt or not is_transient_model_error(str(exc)):
                raise
            sleep(base_delay_s * (attempt + 1))

    msg = "unreachable: retry loop exhausted without return or raise"
    raise RuntimeError(msg)


# ── Demo ──────────────────────────────────────────────────────────────────
#
# A pair of fake exception classes stand in for provider-specific ones.
# A ``FlakyModel`` records call count so we can inspect retry behavior.


class FakeAuthError(Exception):
    """Stand-in for ``AuthenticationError`` — must NOT trigger retry."""


class FakeRateLimitError(Exception):
    """Stand-in for a 429-class error — SHOULD trigger retry."""


class FlakyModel:
    """Fail the first ``fail_count`` calls, then return a sentinel string."""

    def __init__(self, *, fail_count: int, exc: Exception) -> None:
        self.calls = 0
        self.fail_count = fail_count
        self.exc = exc

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.fail_count:
            raise self.exc
        return f"ok after {self.calls} call(s)"


def main() -> None:
    print("Stage 20 — Transient Retry / Backoff\n")

    print("Predicate samples:")
    for sample in [
        "anthropic 529 overloaded_error: please retry",
        "OpenAI 429 rate limit exceeded",
        "Read timed out after 60s",
        "AuthenticationError: invalid api key",
        "NotFoundError: model claude-no-such-model not available",
    ]:
        print(f"  is_transient({sample!r}) = {is_transient_model_error(sample)}")

    print("\nRetry succeeds (transient — 2 failures, then ok):")
    flaky = FlakyModel(fail_count=2, exc=FakeRateLimitError("429 rate limit"))
    out = retry_on_transient(flaky, max_attempts=4, base_delay_s=0.0)
    print(f"  result : {out!r}")
    print(f"  calls  : {flaky.calls}  (1 success after 2 transient failures)")

    print("\nNo retry (deterministic — auth error):")
    auth = FlakyModel(fail_count=99, exc=FakeAuthError("AuthenticationError: bad key"))
    try:
        retry_on_transient(auth, max_attempts=4, base_delay_s=0.0)
    except FakeAuthError as exc:
        print(f"  raised {type(exc).__name__} immediately (calls = {auth.calls})")

    print("\nGives up after exhausting retries:")
    forever = FlakyModel(fail_count=99, exc=FakeRateLimitError("529 overloaded"))
    try:
        retry_on_transient(forever, max_attempts=3, base_delay_s=0.0)
    except FakeRateLimitError as exc:
        print(f"  raised {type(exc).__name__} after {forever.calls} attempt(s)")

    print("\n" + "=" * 60)
    print("Retry only on transient errors.  Surface deterministic errors")
    print("immediately so they don't masquerade as flakes.")


if __name__ == "__main__":
    main()
