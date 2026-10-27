# Stage 19 — Outer-Agent Subprocess

## 1. Goal

Launch the outer Deep Agent in a separate Python process so its
`deepagents`, `langchain`, and `langgraph` versions are independent of
whatever the inner agent's repo pins — the same pattern the source uses
with `uv run --project <deepagents_root>`.

## 2. What changed from previous stage

- New `OuterAgentRequest` and `OuterAgentResult` dataclasses define
  the wire format the harness and child agree on.
- New `run_outer_agent_subprocess(request, proposer_workspace)`
  serializes the request, spawns the child, reads the result, and
  saves `stdout.log` / `stderr.log` to the workspace.
- New `child_main(request_path, result_path)` is the entrypoint the
  fresh process boots into; selectable as a real Deep Agent via
  `BETTER_HARNESS_USE_LLM=1` or as a deterministic stub by default
  (so the walkthrough runs without spending tokens).
- `_build_command(...)` is the single line to switch from
  `sys.executable` to `["uv", "run", "--project", ..., "python",
  "-m", ...]` for full dependency-tree isolation.

## 3. Run it

```bash
uv run python stages_c/stage_19_outer_agent_subprocess.py
```

Optional, opt-in real Deep Agent (spends API tokens):

```bash
BETTER_HARNESS_USE_LLM=1 uv run python stages_c/stage_19_outer_agent_subprocess.py
```

## 4. Walkthrough

The wire format is two dataclasses:

```python
@dataclass(frozen=True)
class OuterAgentRequest:
    workspace_root: str
    system_prompt: str
    user_message: str
    max_turns: int = 20

@dataclass(frozen=True)
class OuterAgentResult:
    final_message: str
    files_written: list[str] = field(default_factory=list)
    error: str | None = None
```

The harness writes the request, spawns the child, captures logs, reads
the result:

```python
def run_outer_agent_subprocess(request, *, proposer_workspace):
    request_path = proposer_workspace / "request.json"
    result_path  = proposer_workspace / "result.json"
    request_path.write_text(json.dumps(asdict(request), indent=2))
    completed = subprocess.run(_build_command(...), env=env, ...)
    (proposer_workspace / "stdout.log").write_text(completed.stdout)
    (proposer_workspace / "stderr.log").write_text(completed.stderr)
    return OuterAgentResult(**json.loads(result_path.read_text()))
```

The child loads the request, runs an agent, writes the result:

```python
def child_main(request_path, result_path):
    request = OuterAgentRequest(**json.loads(request_path.read_text()))
    result  = _run_deep_agent(request, ...)  # or _run_stub_agent
    result_path.write_text(json.dumps(asdict(result), indent=2))
```

## 5. Why this abstraction matters

Both agents want to import `langchain` / `langgraph` / `deepagents`,
potentially at incompatible versions.  Process isolation gives each
its own interpreter, its own `site-packages`, its own dependency
graph.  Subprocess + `uv --project` solves the version-compatibility
problem without forcing the user to align dependency trees by hand.

Logs and result files on disk are also a debugging gift: when an
iteration goes sideways at 3am, the harness has already saved
`stdout.log`, `stderr.log`, `request.json`, and `result.json` next
to the variant that produced them.

## 6. Tradeoffs vs simpler approach

In-process invocation (just `import` the outer agent and call it) is
faster and easier — no JSON, no logs, no subprocess.  It's the right
default when both agents share dependencies.  The moment they don't,
you need either a coordinated upgrade across both repos or process
isolation.  The latter is far cheaper.

## 7. LangChain mapping

The outer agent (when the LLM path is enabled) is still a LangChain
agent constructed by Deep Agents.  The novelty is *where* it lives:
in a different interpreter from the harness invoking it.

## 8. LangGraph mapping

`create_deep_agent(...)` returns a compiled `StateGraph` as before.
The graph runs entirely inside the child process; the harness sees
only the JSON result.

## 9. Aha insight

Process isolation is dependency isolation.  If two agents need
different versions of the same library, give them different
processes.  A JSON request + a JSON result is a small enough
contract to keep across that boundary indefinitely.

## 10. Common mistake

Forgetting to capture `stderr` to disk.  When the child crashes
during interpreter startup, the only signal is a non-zero return
code; if `stderr` was discarded, you have no way to diagnose what
went wrong.  Always save both streams.

## 11. Simpler alternative & why it breaks later

`importlib.reload` of the outer agent's modules to "reset" it
between iterations.  Looks clever; in practice, half of LangChain's
import-time wiring (Pydantic models, registries, env-driven
defaults) doesn't reload cleanly.  Subprocess gives a guaranteed
fresh state every time.

## 12. Exercise

Replace `_build_command` with the `uv run --project ...` form,
pointing at a checkout of `deepagents` you have on disk.  Confirm
the child process picks up the alternate `deepagents` version (you
can verify by printing `deepagents.__version__` from `child_main`).

## 13. What Tier C adds here

Stage 19 is part of Tier C.  The final stage (20) hardens every LLM
call site against transient provider errors with a small retry loop,
so a single 529 doesn't kill an hours-long optimization run.
