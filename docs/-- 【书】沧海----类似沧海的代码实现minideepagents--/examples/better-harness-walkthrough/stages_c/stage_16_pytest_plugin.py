"""Stage 16 — Pytest Plugin.

Hook ``patch_from_env()`` into pytest's lifecycle by packaging it as a
tiny pytest plugin and loading it via the ``PYTEST_PLUGINS`` env var.
The plugin runs at pytest startup, *before* any test module is collected
— which is the only place a patch to a module attribute reliably takes
effect for the inner agent's tests.

Run::

    uv run python stages_c/stage_16_pytest_plugin.py
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

VARIANT_ENV = "BETTER_HARNESS_VARIANT_FILE"

# The attribute the test will assert was patched.
BASE_PROMPT = "You are a helpful assistant."
MAX_TURNS = "1"


# ── Variant + patch helpers (same shape as stage 15) ──────────────────────


@dataclass(frozen=True)
class Variant:
    label: str
    overrides: dict[str, str]

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> Variant:
        payload = json.loads(path.read_text())
        return cls(label=payload["label"], overrides=payload["overrides"])


def patch_module_attrs(overrides: dict[str, str]) -> None:
    for target, value in overrides.items():
        module_name, separator, attribute = target.partition(":")
        if not separator:
            msg = f"invalid module_attr target {target!r}; expected module:attribute"
            raise ValueError(msg)
        module = importlib.import_module(module_name)
        setattr(module, attribute, value)


def patch_from_env() -> None:
    """Read the env-pinned variant file (if any) and apply it."""
    raw_path = os.environ.get(VARIANT_ENV)
    if not raw_path:
        return
    variant = Variant.load(Path(raw_path))
    patch_module_attrs(variant.overrides)


# ── The plugin module ─────────────────────────────────────────────────────
#
# In a real package this would be a top-level module like
# ``better_harness_walkthrough_plugin.py``.  The walkthrough writes it to
# a temp dir and adds that dir to PYTHONPATH so the demo runs in
# isolation.

PLUGIN_SOURCE = """\
'''Pytest plugin for the better-harness walkthrough — apply a variant.

Loaded automatically when ``PYTEST_PLUGINS`` includes this module name.
The body runs once at pytest startup, before collection.
'''
from stages_c.stage_16_pytest_plugin import patch_from_env

patch_from_env()
"""

# A throwaway test that proves the patch landed before collection.
TEST_SOURCE = """\
from stages_c.stage_16_pytest_plugin import BASE_PROMPT, MAX_TURNS


def test_prompt_is_patched():
    # The plugin ran at startup; this module-level value should reflect
    # the variant the harness wrote to BETTER_HARNESS_VARIANT_FILE.
    assert BASE_PROMPT.startswith("You are a careful math assistant"), (
        f"prompt was not patched: {BASE_PROMPT!r}"
    )

def test_max_turns_is_patched():
    assert MAX_TURNS == '3', (
        f"max turns was not patched: {MAX_TURNS!r}"
    )
"""


def main() -> None:
    print("Stage 16 — Pytest Plugin\n")

    walkthrough_root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory(prefix="bh_stage16_") as tmpdir:
        tmp = Path(tmpdir)
        plugin_dir = tmp / "plugin"
        plugin_dir.mkdir()
        plugin_path = plugin_dir / "bh_stage16_plugin.py"
        plugin_path.write_text(PLUGIN_SOURCE)

        test_dir = tmp / "tests"
        test_dir.mkdir()
        test_path = test_dir / "test_prompt.py"
        test_path.write_text(TEST_SOURCE)

        variant = Variant(
            label="iter-001",
            overrides={
                "stages_c.stage_16_pytest_plugin:BASE_PROMPT": (
                    "You are a careful math assistant. Always use the calculator."
                ),
                "stages_c.stage_16_pytest_plugin:MAX_TURNS": "3",
            },
        )
        variant_path = tmp / "variant.json"
        variant.save(variant_path)

        print(f"plugin   → {plugin_path}")
        print(f"test     → {test_path}")
        print(f"variant  → {variant_path}\n")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(walkthrough_root), str(plugin_dir), env.get("PYTHONPATH", "")],
        )
        env[VARIANT_ENV] = str(variant_path)
        env["PYTEST_PLUGINS"] = "bh_stage16_plugin"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--rootdir",
                str(test_dir),
                str(test_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        print("─ pytest stdout ─")
        print(textwrap.indent(completed.stdout.rstrip() or "(empty)", "  "))
        if completed.stderr.strip():
            print("─ pytest stderr ─")
            print(textwrap.indent(completed.stderr.rstrip(), "  "))
        print(f"\nreturncode = {completed.returncode}")

        verdict = "✓ plugin patched the module before collection" if completed.returncode == 0 else "✗ test failed"
        print(f"\n{verdict}")


if __name__ == "__main__":
    main()
