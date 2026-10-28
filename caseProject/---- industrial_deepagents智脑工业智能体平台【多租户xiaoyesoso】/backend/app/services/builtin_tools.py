"""Platform-provided function tools and the tool catalog metadata.

Three layers of tools exist in this platform:
1. harness tools mounted automatically by deepagents (fs tools + `task` subagent,
   plus `execute` when a sandbox backend is used);
2. platform function tools below, opt-in per agent;
3. capability switches: sandbox (execute) and planning (write_todos).
"""
from __future__ import annotations

import ast
import operator
from datetime import datetime, timezone

from langchain_core.tools import tool

from ..util import top_words, truncate
from .industrial_tools import INDUSTRIAL_TOOLS

_ALLOWED_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        # Guard against pathological exponents e.g. 9**9**9
        if isinstance(node.op, ast.Pow):
            left, right = _safe_eval(node.left), _safe_eval(node.right)
            if abs(right) > 100:
                raise ValueError("exponent too large")
            return left ** right
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand))
    raise ValueError("only arithmetic expressions with numbers are allowed")


@tool
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression safely (+ - * / // % **).

    Example input: "(123 * 456) / 2". No function calls, names or imports are allowed.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)
        return f"{expression.strip()} = {result}"
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
        return f"ERROR: cannot evaluate expression: {exc}"


@tool
def current_datetime() -> str:
    """Return the current date and time in ISO-8601 (UTC) plus a local timestamp."""
    now = datetime.now(timezone.utc)
    return f"UTC: {now.isoformat(timespec='seconds')}"


@tool
def word_count(text: str, top_k: int = 10) -> str:
    """Count characters/words in text and return the most frequent words.

    Handles English words by whitespace tokens and individual Chinese characters.
    """
    if not text:
        return "ERROR: empty text"
    char_count = len(text)
    no_space = len(text.replace(" ", "").replace("\n", ""))
    words = text.split()
    freq = top_words(text, top_k)
    freq_str = ", ".join(f"{w}:{c}" for w, c in freq.items()) or "(none)"
    return (
        f"characters: {char_count}, non-space characters: {no_space}, "
        f"whitespace words: {len(words)}, top words: {freq_str}"
    )


def _duckduckgo_search(query: str, max_results: int) -> list[dict]:
    """Run one DuckDuckGo text search via the free `ddgs` package (no API key)."""
    from ddgs import DDGS

    return DDGS().text(
        query=query, region="zh-cn", safesearch="moderate", max_results=max_results,
    )


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web with DuckDuckGo (free, no API key).

    Use it when the question needs fresh public information (new standards,
    vendor announcements, public technical docs) that local tools do not cover.
    Returns a numbered list of results (title / URL / snippet) or an ERROR: text
    when the search backend is unreachable — then answer from local knowledge
    and tell the user that live search is unavailable.

    Args:
        query: Search keywords (include standard numbers / model names when relevant).
        max_results: Number of results to return, 1-8, default 5.
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: query 不能为空，请提供检索关键词。"
    try:
        count = max(1, min(int(max_results), 8))
        rows = _duckduckgo_search(query, count)
    except Exception as exc:  # noqa: BLE001 - degrade instead of failing the run
        return f"ERROR: 联网检索暂不可用（{type(exc).__name__}: {exc}），请基于本地知识库回答并告知用户。"
    if not rows:
        return "未检索到相关公开资料。"
    parts = []
    for i, r in enumerate(rows, 1):
        title = str(r.get("title") or "").strip()
        href = str(r.get("href") or "").strip()
        body = truncate(str(r.get("body") or "").strip(), 300)
        parts.append(f"[{i}] {title}\n{href}\n{body}")
    return truncate("\n\n".join(parts), 4000)


def ________own业务工具(self):pass
PLATFORM_TOOLS = [calculate, current_datetime, word_count, web_search] + INDUSTRIAL_TOOLS
PLATFORM_TOOL_MAP = {t.name: t for t in PLATFORM_TOOLS}


_TOOL_LABELS = {
    "calculate": "计算器",
    "current_datetime": "当前时间",
    "word_count": "文本统计",
    "web_search": "联网搜索",
    "query_design_rules": "设计规范检索",
    "shaft_size_calculator": "井道尺寸计算",
    "process_route": "工艺路线查询",
    "equipment_params": "设备参数查询",
    "after_sales_policy": "售后规则查询",
}
_TOOL_DESCRIPTIONS = {
    "calculate": "安全算术表达式求值（仅数字与 + - * / // % **）",
    "current_datetime": "获取当前 UTC 日期时间",
    "word_count": "文本字数/词数统计与高频词",
    "web_search": "DuckDuckGo 免费联网检索公开资料（新标准、厂家公告、公开技术文档），无需 API Key",
    "query_design_rules": "检索工业大脑中的电梯设计标准条款（井道、载重、速度、开门型式等）",
    "shaft_size_calculator": "按梯型/载重/速度/轿厢/开门/对重计算最小井道宽度与深度",
    "process_route": "查询非标订单标准工艺路线与会签节点",
    "equipment_params": "查询主机、控制柜、门系统、轿厢等设备参数",
    "after_sales_policy": "查询质保期限、维保周期与维修响应等售后规则",
}
def platform_tool_meta() -> list[dict]:
    return [
        {
            "name": t.name,
            "label": _TOOL_LABELS.get(t.name, t.name),
            "description": _TOOL_DESCRIPTIONS.get(t.name, t.description),
        }
        for t in PLATFORM_TOOLS
    ]



# Order mirrors the official harness table:
# https://docs.langchain.com/oss/python/deepagents/tools#built-in-harness-tools
HARNESS_TOOL_META = [
    {"name": "ls", "label": "列目录", "description": "列出虚拟文件系统目录内容"},
    {"name": "read_file", "label": "读文件", "description": "读取文件（支持分页与多模态）"},
    {"name": "write_file", "label": "写文件", "description": "创建或覆盖文件"},
    {"name": "edit_file", "label": "编辑文件", "description": "精确字符串替换"},
    {"name": "delete", "label": "删除", "description": "删除文件或递归目录（deepagents>=0.7）"},
    {"name": "glob", "label": "Glob", "description": "按通配符查找文件"},
    {"name": "grep", "label": "Grep", "description": "文件内容检索"},
    {"name": "execute", "label": "Shell 执行", "description": "在沙箱内执行 shell 命令（仅 sandbox 后端，需开启代码执行）"},
    {"name": "task", "label": "子 Agent", "description": "派发隔离子 Agent 处理子任务"},
]



CAPABILITY_META = [
    {
        "name": "sandbox_enabled",
        "label": "本地代码执行 (execute)",
        "description": "启用 deepagents LocalShellBackend，Agent 可在隔离工作目录中执行 shell 命令（本地沙箱，非强隔离，生产建议换远程沙箱）",
        "risk": True,
    },
    {
        "name": "planning_enabled",
        "label": "任务规划 (write_todos)",
        "description": "挂载 TodoListMiddleware，复杂多步任务时自动维护待办列表",
        "risk": False,
    },
]


def ________all(self):pass
def tool_catalog() -> dict:
    return {
        "harness": HARNESS_TOOL_META,
        "platform": platform_tool_meta(),
        "capabilities": CAPABILITY_META,
    }
