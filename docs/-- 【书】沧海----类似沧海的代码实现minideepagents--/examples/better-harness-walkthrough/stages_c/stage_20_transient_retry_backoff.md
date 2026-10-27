# Stage 20 — Transient Retry / Backoff

## 1. Goal

Survive transient provider errors (overloaded, 429, 529, timeout, rate
limit) by wrapping every LLM call in a small retry loop — while
*surfacing* deterministic errors (auth, not-found, validation)
immediately, so they don't masquerade as flakes.

## 2. What changed from previous stage

- New `TRANSIENT_SUBSTRINGS` allowlist of lowercased substrings that
  identify transient errors.
- New `is_transient_model_error(message) -> bool` predicate that
  matches against that allowlist.
- New `retry_on_transient(fn, *, max_attempts, base_delay_s, sleep)`
  generic wrapper: runs `fn()`, retries only when the exception
  matches the predicate, gives up after `max_attempts`, and re-raises
  deterministic errors immediately.
- Demo with a `FlakyModel` shows three scenarios: transient-then-ok,
  deterministic-immediate-raise, and transient-exhaust.

## 3. Run it

```bash
uv run python stages_c/stage_20_transient_retry_backoff.py
```

## 4. Walkthrough

The predicate is a plain substring check:

```python
TRANSIENT_SUBSTRINGS = ("overloaded", "rate limit", "timeout",
                        "timed out", "429", "529", ...)

def is_transient_model_error(message: str) -> bool:
    lowered = message.lower()
    return any(needle in lowered for needle in TRANSIENT_SUBSTRINGS)
```

The retry loop is equally small:

```python
def retry_on_transient(fn, *, max_attempts=4, base_delay_s=2.0,
                       sleep=time.sleep):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            last = attempt == max_attempts - 1
            if last or not is_transient_model_error(str(exc)):
                raise
            sleep(base_delay_s * (attempt + 1))
```

The injected `sleep` lets tests run without wall-clock waits.

Wrap an LLM call by closing over its arguments:

```python
result = retry_on_transient(lambda: model.invoke(messages))
```

## 5. Why this abstraction matters

A single 529 mid-run kills hours of optimization work.  With this
wrapper, transient hiccups are absorbed; the optimization run still
finishes.  Without it, every "robust" eval pipeline eventually grows
its own ad-hoc try/except — usually the wrong one (catch-all,
retries-on-auth-too).  Centralizing it as one tiny helper keeps the
allowlist auditable.

## 6. Tradeoffs vs simpler approach

You could rely on the provider SDK's built-in retry (some have one).
That's fine when you trust the SDK's choice of which errors to retry
on; not all of them retry on 529 or on the right timeout class.  An
explicit wrapper here is a single audit point you control.

## 7. LangChain mapping

LangChain's `init_chat_model` returns a model that may have its own
retry policy.  This wrapper sits *outside* that — it retries the
*entire call*, including any LangChain-level callback dispatch, not
just the network request.  Layered retries are fine; they compose.

## 8. LangGraph mapping

A LangGraph node can use this wrapper inside its body.  An
alternative is to encode retries as a `Send` loop with a state
counter; that's more powerful (visibility, checkpointing) but more
machinery than most call sites need.

## 9. Aha insight

The difference between research code and production code is often
just a retry loop in the right place — and the loop's *predicate* is
where the design lives, not the loop body.

## 10. Common mistake

Catching `Exception` and retrying on *anything*.  This silently masks
real bugs: an `AuthenticationError` should fail loudly so you fix
your env, not retry six times and time out.  Always retry on a
narrow allowlist; never retry on a broad blocklist.

## 11. Simpler alternative & why it breaks later

A bare `for _ in range(3): try: ... except Exception: continue` works
on the day you write it.  It silently retries on `KeyboardInterrupt`,
`SystemExit`, syntax errors thrown from `.invoke()`, schema validation
errors from your own code.  When you eventually need to debug *why*
the candidate variant always "passes", the missing distinction is
this stage's whole point.

## 12. Exercise

Add an `unrecoverable: tuple[type[Exception], ...] = ()` parameter
to `retry_on_transient` that always re-raises immediately for those
exception types, even if their message looks transient.  Useful when
a custom error class shouldn't ever be retried on regardless of its
text.

## 13. What Tier C adds here

This stage closes Tier C and the walkthrough.  The reader now has the
end-to-end picture: a Tier A conceptual rebuild, a Tier B faithful
single-machine harness, and a Tier C production crust ready to run
inside a real eval pipeline.
