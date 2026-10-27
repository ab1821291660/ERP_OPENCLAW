"""Stage 15 — Variant Env Handoff.

Apply a ``Variant`` to a *fresh* Python process via an env-var handoff:
the harness writes the variant to disk, sets ``BETTER_HARNESS_VARIANT_FILE``,
and the child process reads the env var and patches itself on import.

Why: in-process ``setattr`` only works when the harness and the inner
agent share a Python interpreter.  Once the inner runs as a subprocess
(which is how real eval runners work), you need a handoff channel.

Run::

    uv run python stages_c/stage_15_variant_env_handoff.py
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

# ── The "protocol" — one env var name + a JSON file shape ──────────────────

VARIANT_ENV = "BETTER_HARNESS_VARIANT_FILE"


# ── A live module-level value the subprocess will read ─────────────────────
#
# Patching changes this attribute *before* any code reads it.  In a real
# inner agent this would be the system prompt the agent is constructed from.

BASE_PROMPT = "You are a helpful assistant."


# ── Variant — JSON-serializable so it can cross a process boundary ────────


@dataclass(frozen=True)
class Variant:
    """A frozen snapshot of surface values, JSON-serializable."""

    label: str
    overrides: dict[str, str]  # "module:attr" → new value

    def save(self, path: Path) -> None:
        """Write the variant to disk as JSON."""
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> Variant:
        """Reconstruct a variant from a JSON file."""
        payload = json.loads(path.read_text())
        return cls(label=payload["label"], overrides=payload["overrides"])


# ── The patch primitive (same as Tier A stage 04) ─────────────────────────


def patch_module_attrs(overrides: dict[str, str]) -> None:
    """Apply ``module:attribute -> value`` overrides via ``setattr``."""
    for target, value in overrides.items():
        module_name, separator, attribute = target.partition(":")
        if not separator:
            msg = f"invalid module_attr target {target!r}; expected module:attribute"
            raise ValueError(msg)
        module = importlib.import_module(module_name)
        setattr(module, attribute, value)


# ── The new piece — the env-driven entrypoint a child process calls ───────


def patch_from_env() -> None:
    """Read the env-pinned variant file (if any) and apply it.

    Safe to call in any Python entrypoint: returns silently if the env
    var is unset, so unpatched runs still work.
    """
    raw_path = os.environ.get(VARIANT_ENV)
    if not raw_path:
        return
    variant = Variant.load(Path(raw_path))
    patch_module_attrs(variant.overrides)


# ── Demo ──────────────────────────────────────────────────────────────────
#
# We spawn a *fresh* subprocess that imports this very module, calls
# ``patch_from_env()``, and prints ``BASE_PROMPT``.  Without the env var
# it sees the base value; with it, the patched value.

CHILD_SCRIPT = """\
from stages_c.stage_15_variant_env_handoff import patch_from_env
patch_from_env()
from stages_c.stage_15_variant_env_handoff import BASE_PROMPT
print(BASE_PROMPT)

"""

# CHILD_SCRIPT = """\
# from stages_c.stage_15_variant_env_handoff import patch_from_env

# from stages_c.stage_15_variant_env_handoff import BASE_PROMPT

# import stages_c.stage_15_variant_env_handoff as eh
# import stages_c.stage_15_variant_env_handoff as veh

# patch_from_env()
# print(BASE_PROMPT)
# print(eh.BASE_PROMPT)
# print(veh.BASE_PROMPT)
# print(eh is veh) # True
# """


def _run_child(env: dict[str, str]) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", CHILD_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    print("completed: ", completed)
    return completed.stdout.strip()


def _build_base_env() -> dict[str, str]:
    """Make sure the child can import this stage by name."""
    walkthrough_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(walkthrough_root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def main() -> None:
    print("Stage 15 — Variant Env Handoff\n")

    base_env = _build_base_env()

    # 1) No env var → the child sees the original module-level value.
    print(f"  child without {VARIANT_ENV}  → BASE_PROMPT = {_run_child(base_env)!r}")

    # 2) Save a Variant to disk, point the env var at it.
    variant = Variant(
        label="iter-001",
        overrides={
            "stages_c.stage_15_variant_env_handoff:BASE_PROMPT": (
                "You are a careful math assistant. "
                "Always use the calculator tool for arithmetic."
            )
        },
    )
    with tempfile.TemporaryDirectory(prefix="bh_stage15_") as tmpdir:
        variant_path = Path(tmpdir) / "variant.json"
        variant.save(variant_path)
        print(f"\n  wrote variant → {variant_path}")
        print(f"  variant payload:\n{variant_path.read_text().rstrip()}")

        env = base_env.copy()
        env[VARIANT_ENV] = str(variant_path)
        out = _run_child(env)
        print(f"\n  child WITH    {VARIANT_ENV} → BASE_PROMPT = {out!r}")

    print("\n" + "=" * 60)
    print("The fresh child process learned the variant from a file path on")
    print("disk + one env var.  No shared in-memory state required.")


if __name__ == "__main__":
    main()
