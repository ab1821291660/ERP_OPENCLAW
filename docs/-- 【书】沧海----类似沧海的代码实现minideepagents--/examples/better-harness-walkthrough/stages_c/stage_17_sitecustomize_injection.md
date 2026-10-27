# Stage 17 — Sitecustomize Injection

## 1. Goal

For non-pytest child processes, install `patch_from_env()` at Python
*interpreter* startup via Python's `site` machinery — so the variant is
applied before the child entrypoint runs its first statement.

## 2. What changed from previous stage

- New `ensure_sitecustomize(runtime_dir) -> Path` writes a one-line
  `sitecustomize.py` whose body calls `patch_from_env()`.
- New `prepend_pythonpath(paths, existing) -> str` builds the
  `PYTHONPATH` string with the runtime dir first.
- Demo spawns a child that never explicitly calls `patch_from_env()`
  yet still observes the patched value — proving the hook fired before
  the child's first import.

## 3. Run it

```bash
uv run python stages_c/stage_17_sitecustomize_injection.py
```

## 4. Walkthrough

The hook file is the smallest possible Python module:

```python
# sitecustomize.py
from stages_c.stage_17_sitecustomize_injection import patch_from_env

patch_from_env()
```

`site.py` runs early in the interpreter startup sequence and imports
`sitecustomize` if it can find one on `sys.path`.  By prepending our
runtime dir to `PYTHONPATH`, we guarantee `site.py` finds *our*
`sitecustomize.py` first:

```python
env["PYTHONPATH"] = prepend_pythonpath(
    [runtime_dir, walkthrough_root], env.get("PYTHONPATH"),
)
env[VARIANT_ENV] = str(variant_path)
```

The child entrypoint never mentions patching:

```python
# child script
from stages_c.stage_17_sitecustomize_injection import BASE_PROMPT
print(BASE_PROMPT)
```

…yet it sees the patched value, because `sitecustomize.py` ran first.

## 5. Why this abstraction matters

Some inner agents are scripts, not test suites.  They have no pytest
lifecycle to plug into.  But they still need the variant applied
*before* any of their modules load — otherwise an early import of the
module containing `BASE_PROMPT` captures the unpatched string.

Python's startup sequence is:

1. interpreter starts
2. `site.py` runs
3. `site.py` imports `sitecustomize` (if any)
4. user entrypoint runs

Step 3 is the earliest user-controllable hook.  It runs *before* the
entrypoint script's first line, before any user import.

## 6. Tradeoffs vs simpler approach

You could ask every inner-agent entrypoint to call `patch_from_env()`
in its `__main__` block.  Works for entrypoints you own.  Falls down
the moment a third-party tool spawns a Python subprocess that imports
your code (debugger, profiler, language server) — those processes
don't know about your harness.  `sitecustomize` covers them all.

## 7. LangChain mapping

None.  Pure CPython startup behavior.

## 8. LangGraph mapping

None.

## 9. Aha insight

If you need code to run *before* anything else, hook the interpreter,
not the application.  `sitecustomize.py` + a `PYTHONPATH` prepend is
the documented hook.

## 10. Common mistake

Putting `sitecustomize.py` somewhere on `PYTHONPATH` *after* a
distribution-installed `sitecustomize` (yes, some distros ship one).
Always *prepend*, never append, so the harness's hook wins.

A second trap: forgetting to also propagate the runtime dir to any
nested subprocesses the child spawns.  If the child re-execs Python
without forwarding `PYTHONPATH`, the grandchild loses the hook.

## 11. Simpler alternative & why it breaks later

`PYTHONSTARTUP` runs only in interactive shells.  `usercustomize.py`
needs `~/.local/lib/python<X.Y>/site-packages` and is shared across
*every* process the user runs — way too broad a hammer for a
per-experiment patch.  `sitecustomize.py` in a per-run runtime dir is
the right precision.

## 12. Exercise

Run the child *without* the runtime dir on `PYTHONPATH` (just remove
that prefix).  Confirm the child prints the unpatched
`"You are a helpful assistant."`, demonstrating that the hook is the
only thing wiring the patch in.

## 13. What Tier C adds here

Stage 17 is part of Tier C.  Stage 18 builds on this groundwork by
parsing the child's pytest output (JUnit XML) into structured
`CaseOutcome` objects so the harness can reason about results
programmatically.
