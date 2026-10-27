# Stage 16 — Pytest Plugin

## 1. Goal

Make `patch_from_env()` run automatically at pytest startup by
packaging it as a tiny pytest plugin and loading it through the
`PYTEST_PLUGINS` env var — so the inner agent's tests see a patched
module before any of them are collected.

## 2. What changed from previous stage

- New `bh_stage16_plugin.py` source — a one-liner that imports the
  stage's `patch_from_env` and calls it.  The module *body* is the
  hook; pytest imports the plugin during startup.
- The harness sets `PYTEST_PLUGINS=bh_stage16_plugin` in the
  subprocess env (alongside `BETTER_HARNESS_VARIANT_FILE`).
- The harness puts the plugin's containing directory on `PYTHONPATH`
  so pytest can find it without modifying the inner agent's repo.
- A throwaway `test_prompt.py` asserts that `BASE_PROMPT` was patched
  by the time the test ran.

## 3. Run it

```bash
uv run python stages_c/stage_16_pytest_plugin.py
```

## 4. Walkthrough

The plugin file is small enough to read in full:

```python
# bh_stage16_plugin.py
from stages_c.stage_16_pytest_plugin import patch_from_env

patch_from_env()
```

That's the entire "plugin".  It works because pytest imports every
module named in `PYTEST_PLUGINS` early in its startup sequence.  Code
at the module's top level runs once, before collection.

The harness side wires three env vars:

```python
env["PYTHONPATH"] = os.pathsep.join(
    [str(walkthrough_root), str(plugin_dir), env.get("PYTHONPATH", "")],
)
env[VARIANT_ENV] = str(variant_path)
env["PYTEST_PLUGINS"] = "bh_stage16_plugin"
```

The test then asserts the module attribute was patched:

```python
from stages_c.stage_16_pytest_plugin import BASE_PROMPT

def test_prompt_is_patched():
    assert BASE_PROMPT.startswith("You are a careful math assistant")
```

If the plugin had not run, the import would see the unpatched
`"You are a helpful assistant."` and the test would fail.

## 5. Why this abstraction matters

The variant must be applied *before* the inner agent's modules load.
A `conftest.py` in the inner repo would also work, but that requires
modifying the target.  `PYTEST_PLUGINS` is the pytest-supported hook
for installing behavior into someone else's process without touching
their code.

## 6. Tradeoffs vs simpler approach

You could write a session-scoped `autouse` fixture, but fixtures run
*after* collection.  Anything captured at module import time (an
agent's compiled prompt, a tool registry, a cached config) would
already be stale.  A plugin's module body runs early enough to win
that race.

## 7. LangChain mapping

None.  The mechanism is below the LangChain layer — it's pytest's
plugin system.

## 8. LangGraph mapping

None.

## 9. Aha insight

Plugins are how you install behavior into someone else's process
without modifying their code.  `PYTEST_PLUGINS=<name>` is the entry
point; everything after that is just a Python module.

## 10. Common mistake

Importing the plugin via a `conftest.py` placed in the inner agent's
repo.  That requires editing the target's source — exactly the
coupling we are trying to avoid.  Env-loaded plugins keep the inner
agent's repo unchanged across every iteration.

## 11. Simpler alternative & why it breaks later

A small wrapper script:

```python
# wrapper.py
from stages_c.stage_16_pytest_plugin import patch_from_env
patch_from_env()
import pytest; pytest.main(...)
```

This works but doesn't help for any pytest invocation the inner
repo's tooling makes that doesn't go through your wrapper (CI,
editor integrations, `make test`).  `PYTEST_PLUGINS` plus `env` is
the hook every pytest path respects.

## 12. Exercise

Add a second module attribute (e.g. a fake `MAX_TURNS = 1`) to the
stage module and a second test asserting that it was patched too.
Confirm a single plugin call covers all targets the variant lists.

## 13. What Tier C adds here

This stage *is* Tier C.  The next stage (17) covers the non-pytest
case — for child processes that aren't running under pytest at all.
