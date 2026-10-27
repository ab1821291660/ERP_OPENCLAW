# Stage 15 — Variant Env Handoff

## 1. Goal

Apply a `Variant` to a *fresh* Python process by writing the variant to
disk and pointing one env var at it — the channel that lets in-process
patching survive a subprocess boundary.

## 2. What changed from previous stage

- New `Variant.save(path)` / `Variant.load(path)` — JSON round-trip so
  the dataclass can cross a process boundary.
- New `VARIANT_ENV = "BETTER_HARNESS_VARIANT_FILE"` constant — the
  agreed env-var name the child reads.
- New `patch_from_env()` — read the env var, load the variant, apply
  `patch_module_attrs`.  Safe to call when the env var is unset (no-op).
- Demo spawns a real subprocess via `sys.executable -c` and shows
  `BASE_PROMPT` differing with vs without `BETTER_HARNESS_VARIANT_FILE`.

## 3. Run it

```bash
uv run python stages_c/stage_15_variant_env_handoff.py
```

## 4. Walkthrough

The handoff has two halves.

The harness side serializes a variant:

```python
variant = Variant(
    label="iter-001",
    overrides={"stages_c.stage_15_variant_env_handoff:BASE_PROMPT": "..."},
)
variant.save(variant_path)
env = {**os.environ, VARIANT_ENV: str(variant_path)}
subprocess.run([sys.executable, "-c", CHILD_SCRIPT], env=env, ...)
```

The child side learns about the variant entirely from disk:

```python
def patch_from_env():
    raw_path = os.environ.get(VARIANT_ENV)
    if not raw_path:
        return
    variant = Variant.load(Path(raw_path))
    patch_module_attrs(variant.overrides)
```

That's the whole "protocol" — one env var name + a JSON file shape.

## 5. Why this abstraction matters

Tier A's `setattr` works only when both sides share a Python
interpreter.  Real eval runners spawn a fresh interpreter per case
(pytest does, Harbor does, anything Docker-y does).  Without a handoff
channel, the subprocess imports the *unpatched* module and the variant
is silently ignored.

A file path + one env var is the smallest channel that crosses every
process boundary Python can spawn into: subprocess, pytest, uv run, even
across container boundaries that share a volume.

## 6. Tradeoffs vs simpler approach

You could pass the variant on the command line as a base64-encoded JSON
blob.  Works for tiny variants; falls apart the moment a surface is a
multi-kilobyte source file (argv length limits + shell quoting).  A file
on disk has no length limit and is independently inspectable while the
run is in flight.

You could also use a Unix domain socket or a queue.  Both work, both
require coordinating server lifetimes across processes you don't fully
control.  A file is the simplest stateless channel.

## 7. LangChain mapping

None.  This stage is pure Python interpreter plumbing.

## 8. LangGraph mapping

None.  Subprocess handoff is below the LangGraph layer.

## 9. Aha insight

Env vars + a JSON file is enough of a "protocol" to pass a variant
across a process boundary.  No RPC framework, no serialization library,
no schema registry — just `json` and `os.environ`.

## 10. Common mistake

Calling `patch_from_env()` *after* the inner agent has already imported
the module the patch targets.  By that point the agent has cached the
old value; subsequent reads will mostly get the new one but anything
constructed during the agent's import sees the stale one.  The earliest
hook (next stage's pytest plugin / stage 17's `sitecustomize`) is what
makes the call reliable.

## 11. Simpler alternative & why it breaks later

Hard-coding the variant in the child script's source (e.g.
`BASE_PROMPT = "..."`).  Trivially works for a one-shot demo; impossible
to script over many candidates without templating Python source — and
templating Python source is a bug factory.  A serialized data object is
the right boundary.

## 12. Exercise

Add a `Variant.load(...)` validator that raises if any `target` doesn't
contain `":"`.  Confirm the child fails fast instead of silently
no-op'ing on a malformed variant file.

## 13. What Tier C adds here

Stage 15 *is* the start of Tier C.  The next stage installs
`patch_from_env()` into pytest's lifecycle so the child doesn't even
need to call it explicitly.
