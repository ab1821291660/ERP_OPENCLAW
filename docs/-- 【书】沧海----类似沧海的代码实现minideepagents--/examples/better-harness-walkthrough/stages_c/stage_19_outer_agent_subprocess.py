"""Stage 19 — Outer-Agent Subprocess.

Run the outer Deep Agent in a separate Python process so its
``deepagents`` / ``langchain`` / ``langgraph`` versions are decoupled
from whatever the inner agent's repo pins.  The harness writes a
request JSON to disk, spawns the entrypoint, and reads a result JSON
back; ``stdout`` and ``stderr`` go to log files alongside.

In the source `examples/better-harness/`, the spawn command is::

    uv run --project <deepagents_root> python -m better_harness.outer_agent ...

For the walkthrough we use ``sys.executable`` so the demo runs without
a second `uv` project on disk.  Switching to the isolated form is a
one-line change to ``_build_command``.

Run::

    uv run python stages_c/stage_19_outer_agent_subprocess.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── The wire format — request and result both live on disk as JSON ────────


@dataclass(frozen=True)
class OuterAgentRequest:
    """Everything the outer agent needs to start."""

    workspace_root: str
    system_prompt: str
    user_message: str
    max_turns: int = 20


@dataclass(frozen=True)
class OuterAgentResult:
    """Everything the harness reads back."""

    final_message: str
    files_written: list[str] = field(default_factory=list)
    error: str | None = None


# ── The harness side ──────────────────────────────────────────────────────


def _build_command(*, request_path: Path, result_path: Path) -> list[str]:
    """Return the ``argv`` to spawn the outer-agent entrypoint.

    Switch this to ``["uv", "run", "--project", deepagents_root,
    "python", "-m", "better_harness_walkthrough.outer_agent",
    str(request_path), str(result_path)]`` to fully isolate the outer
    agent's dependency tree from the inner's.  Uses ``sys.executable``
    here so the walkthrough runs without a second `uv` project.
    """
    return [
        sys.executable,
        "-m",
        "stages_c.stage_19_outer_agent_subprocess",
        "--child",
        str(request_path),
        str(result_path),
    ]


def run_outer_agent_subprocess(
    request: OuterAgentRequest,
    *,
    proposer_workspace: Path,
) -> OuterAgentResult:
    """Run the outer agent in a fresh Python process.

    Steps:
        1. Serialize ``request`` to ``request.json``.
        2. Spawn the entrypoint, passing both file paths as argv.
        3. Save ``stdout`` and ``stderr`` to log files in
           ``proposer_workspace``.
        4. Deserialize ``result.json`` and return.
    """
    request_path = proposer_workspace / "request.json"
    result_path = proposer_workspace / "result.json"
    request_path.write_text(json.dumps(asdict(request), indent=2))

    walkthrough_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(walkthrough_root) + os.pathsep + env.get("PYTHONPATH", "")
    )

    completed = subprocess.run(
        _build_command(request_path=request_path, result_path=result_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (proposer_workspace / "stdout.log").write_text(completed.stdout)
    (proposer_workspace / "stderr.log").write_text(completed.stderr)

    if completed.returncode != 0 or not result_path.exists():
        return OuterAgentResult(
            final_message="",
            files_written=[],
            error=(
                f"subprocess returncode={completed.returncode}; "
                f"stderr={completed.stderr.strip()[:200]}"
            ),
        )
    payload = json.loads(result_path.read_text())
    return OuterAgentResult(**payload)


# ── The child side ────────────────────────────────────────────────────────


def child_main(request_path: Path, result_path: Path) -> None:
    """Outer-agent entrypoint, run under a fresh interpreter."""
    payload = json.loads(request_path.read_text())
    request = OuterAgentRequest(**payload)
    workspace = Path(request.workspace_root)

    # Real isolation calls ``create_deep_agent`` from the *separate* uv
    # project's ``deepagents``.  For the walkthrough demo we use a
    # deterministic stub so the stage runs without spending tokens.
    # Set ``BETTER_HARNESS_USE_LLM=1`` to switch to a real Deep Agent.
    if os.environ.get("BETTER_HARNESS_USE_LLM") == "1":
        result = _run_deep_agent(request, workspace)
    else:
        result = _run_stub_agent(request, workspace)

    result_path.write_text(json.dumps(asdict(result), indent=2))


def _run_stub_agent(
    request: OuterAgentRequest, workspace: Path,
) -> OuterAgentResult:
    """Deterministic stand-in for the real Deep Agent.

    Reads ``/current/prompt.txt`` from the proposer workspace, replaces
    it with a hand-crafted improved prompt, and reports what changed.
    """
    files_written: list[str] = []
    current = workspace / "current" / "prompt.txt"
    if current.exists():
        improved = (
            "You are a careful math assistant.  For ANY arithmetic, "
            "ALWAYS call the `calculator` tool.  After getting the "
            "tool's numeric result, return ONLY that number."
        )
        current.write_text(improved)
        files_written.append(str(current.relative_to(workspace)))
    return OuterAgentResult(
        final_message=(
            f"[stub] processed request from {request.user_message[:40]!r}; "
            f"edited {len(files_written)} file(s)"
        ),
        files_written=files_written,
    )


def _run_deep_agent(
    request: OuterAgentRequest, workspace: Path,
) -> OuterAgentResult:
    """Real Deep-Agent path; opt-in via ``BETTER_HARNESS_USE_LLM=1``."""
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    from config import get_outer_model

    backend = FilesystemBackend(root_dir=str(workspace), virtual_mode=True)
    agent = create_deep_agent(
        model=get_outer_model(),
        system_prompt=request.system_prompt,
        backend=backend,
    )
    invocation = agent.invoke(
        {"messages": [{"role": "user", "content": request.user_message}]},
        config={"recursion_limit": request.max_turns},
    )
    final = invocation["messages"][-1].content
    files_written = [
        str(path.relative_to(workspace))
        for path in (workspace / "current").rglob("*")
        if path.is_file()
    ]
    return OuterAgentResult(
        final_message=final if isinstance(final, str) else str(final),
        files_written=files_written,
    )


# ── Demo ──────────────────────────────────────────────────────────────────


def _demo() -> None:
    print("Stage 19 — Outer-Agent Subprocess\n")

    with tempfile.TemporaryDirectory(prefix="bh_stage19_") as tmpdir:
        proposer = Path(tmpdir) / "proposer"
        proposer.mkdir()
        (proposer / "current").mkdir()
        (proposer / "current" / "prompt.txt").write_text(
            "You are a helpful assistant.",
        )
        (proposer / "task.md").write_text(
            "# Task\nImprove /current/prompt.txt for arithmetic correctness.\n",
        )

        request = OuterAgentRequest(
            workspace_root=str(proposer),
            system_prompt="You are a harness-improver Deep Agent.",
            user_message="Read /task.md, then improve /current/prompt.txt.",
        )
        print("Request (written to disk for the child):")
        print(textwrap.indent(json.dumps(asdict(request), indent=2), "  "))

        result = run_outer_agent_subprocess(
            request, proposer_workspace=proposer,
        )
        print("\nResult (read back from disk):")
        print(textwrap.indent(json.dumps(asdict(result), indent=2), "  "))

        print("\nFinal /current/prompt.txt:")
        print(textwrap.indent(
            (proposer / "current" / "prompt.txt").read_text(), "  "))

        print("\nLogs preserved:")
        print(f"  stdout.log → {proposer / 'stdout.log'}")
        print(f"  stderr.log → {proposer / 'stderr.log'}")

    print("\n" + "=" * 60)
    print("The outer agent ran in a separate process.  Switch the spawn")
    print("command to `uv run --project <deepagents_root>` to fully")
    print("isolate the outer agent's dependency tree from the inner's.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage 19 — outer-agent subprocess")
    parser.add_argument(
        "--child",
        nargs=2,
        metavar=("REQUEST", "RESULT"),
        help="Run as the child entrypoint (called by the harness, not by humans)",
    )
    args = parser.parse_args(argv)
    if args.child:
        child_main(Path(args.child[0]), Path(args.child[1]))
    else:
        _demo()


if __name__ == "__main__":
    main()
