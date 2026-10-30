import os
import sys

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, LocalShellBackend
from langgraph.checkpoint.memory import InMemorySaver

from agent.my_backend import DictBackend
from agent.my_llm import llm
from agent.my_tools import web_search

checkpointer = InMemorySaver()


agent = create_deep_agent(  # create_agent
    model=llm,
    tools=[web_search],
    checkpointer=checkpointer,
    backend=DictBackend(),
    system_prompt='你是一个助手，请根据用户输入的指令，进行相应的操作。'
)