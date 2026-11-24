"""Deep agent with LangSmith sandbox - graph-based architecture."""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState


from langsmith.sandbox import SandboxClient ##========
from langsmith_backend import LangSmithBackend ##===================================##===================================
class SandboxAgentState(MessagesState):
    """Graph state that includes sandbox connection info."""
    sandbox_id: str | None = None




TEMPLATE_NAME = "python-sandbox"
TEMPLATE_IMAGE = "ubuntu:24.04"
def create_sandbox(state: SandboxAgentState) -> dict[str, Any]:
    """Create LangSmith sandbox and store its ID in state."""
    client = SandboxClient()##========
    # Ensure template exists
    try:
        client.get_template(TEMPLATE_NAME)##========
    except Exception:
        print(f"Creating template '{TEMPLATE_NAME}'...")
        client.create_template(name=TEMPLATE_NAME, image=TEMPLATE_IMAGE)##========


    # Create sandbox
    print("Creating sandbox...")
    sb = client.create_sandbox(template_name=TEMPLATE_NAME, timeout=180)##======== ##===================================

    # Verify sandbox is ready
    result = sb.run("echo ready", timeout=5)##===================================
    if result.exit_code != 0:
        raise RuntimeError("Sandbox readiness check failed")
    print(f"Sandbox ready: {sb.name}")
    return {"sandbox_id": sb.name}



def run_agent(state: SandboxAgentState) -> dict[str, Any]:
    """Run deep agent using sandbox from state."""
    if not state["sandbox_id"]:
        raise RuntimeError("No sandbox_id in state - create_sandbox must run first")
    # Reconnect to sandbox
    client = SandboxClient()##========
    sb = client.get_sandbox(name=state["sandbox_id"])##========


    backend = LangSmithBackend(sb)##===================================##===================================
    # Create deep agent with the sandbox backend
    agent = create_deep_agent(
        backend=backend,
        system_prompt="You are a helpful coding assistant with filesystem access via a sandbox.",
        checkpointer=MemorySaver(),
    )

    # Invoke the agent with the current messages
    result = agent.invoke(
        {"messages": state["messages"]},
        config={"configurable": {"thread_id": state["sandbox_id"]}},
    )
    return {"messages": result["messages"]}


def cleanup_sandbox(state: SandboxAgentState) -> dict[str, Any]:
    """Cleanup sandbox after agent completes."""
    if state["sandbox_id"]:
        print(f"Cleaning up sandbox: {state['sandbox_id']}...")
        client = SandboxClient()##========
        try:
            client.delete_sandbox(state["sandbox_id"])##========
            print("Sandbox deleted.")
        except Exception as e:
            print(f"Warning: Failed to delete sandbox: {e}")
    return {"sandbox_id": None}


builder = StateGraph(SandboxAgentState)
builder.add_node("create_sandbox", create_sandbox)
builder.add_node("run_agent", run_agent)
builder.add_node("cleanup_sandbox", cleanup_sandbox)


builder.add_edge(START, "create_sandbox")
builder.add_edge("create_sandbox", "run_agent")
builder.add_edge("run_agent", "cleanup_sandbox")
builder.add_edge("cleanup_sandbox", END)
graph = builder.compile()

