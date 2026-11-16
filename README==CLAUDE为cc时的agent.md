# ERP OPENCLAW Agent Context

本文件是 `ERP_OPENCLAW` 的自包含开发上下文。即使 IDE 只打开当前目录，也应能据此定位代码、启动服务和判断系统边界。

## 工程定位

`ERP_OPENCLAW` 是整个仓库的核心：基于 DeepAgents `0.4.12` 的 ERP 智能采购助手。它通过主 Agent 编排两个子 Agent，通过 MCP 访问 Java ERP 数据和可视化能力，在 OpenSandbox 中执行文件与技能工作，并由 FastAPI + Vue 提供流式交互界面。

完整使用说明见 `README.md`，前端说明见 `frontend/README.md`。在完整仓库布局中，Java 业务服务位于相邻目录 `../motorcycle-parts-procurement-system/`。

## 运行链路与端口

```text
frontend/ (Vue :3000)
  -> src/api_view/ (FastAPI :8090)
  -> src/agent/ (Orchestrator + SubAgents)
  -> src/mcp_server/ (ERP MCP :8000/mcp)
  -> ../motorcycle-parts-procurement-system/ (Spring Boot :8080/api)
```

外部依赖还包括 MySQL、MongoDB checkpoint、OpenSandbox、模型 API 与魔塔可视化 MCP。`start_web.py` 只管理 `8090` 和 `3000`，不会启动 Java 或 ERP MCP。

## 代码地图

| 路径 | 责任 |
|---|---|
| `src/agent/main_agent.py` | 主 Agent graph factory、工具池、CompositeBackend、中间件栈 |
| `src/agent/config.py` | 模型、沙箱、MongoDB、Store 和路径配置 |
| `src/agent/subagents/configs/` | 采购分析与采购订单子 Agent 的提示词、工具和 HITL 配置 |
| `src/agent/middlewares/` | 上下文注入、技能同步、记忆更新、摘要、健康检查与熔断 |
| `src/agent/backends/` | per-user OpenSandbox 创建、代理和生命周期管理 |
| `src/agent/tools/` | MCP 客户端、图表聚合、搜索、人工补数和文件下载 |
| `src/agent/memory/AGENTS.md` | 运行时行为准则；启动时上传到沙箱 `/AGENTS.md` |
| `src/skills/` | 主 Agent 与采购分析技能，按需渐进加载 |
| `src/mcp_server/` | 将 Java REST API 封装为 FastMCP tools |
| `src/api_view/` | FastAPI 生命周期、SSE 对话、HITL 恢复和历史记录 |
| `frontend/` | Vue 对话 UI 与 SSE 事件消费 |

## 一次请求如何执行

1. 前端 → `/api/chat/stream` 发送用户消息。
2. FastAPI 为该用户获取 / 创建独立沙箱，并用 graph factory 创建本次 agent graph。
3. 主 Agent 注入上下文与记忆，按需同步 skills，判断直接回答还是委派子 Agent。
4. `procurement-analyst` 查 ERP 数据 / 抓供应商页 / 分析 / 出报告；`procurement-order` 校验订单字段并调用订单工具。
5. ERP MCP 把工具调用转成 Java REST 请求；**创建 / 更新订单前** LangGraph `interrupt` 等待前端审批。
6. token、工具状态、图片、中断、完成信号通过 SSE 持续回传；checkpoint 写 MongoDB 以便会话恢复。

## 三类状态存储（不要混淆）

- **MongoDB checkpoint**：LangGraph 对话状态，用于中断 / 会话恢复。
- **StoreBackend `/memories/`**：用户长期记忆 + 持久化技能（经 `CompositeBackend` 路由）。
- **OpenSandbox 文件系统**：默认工作目录、生成的报告、下载文件（`src/download/`）。

## 开发约定

- Python 版本最低 `3.10`，源码根为 `src`；命令使用 `PYTHONPATH=src`。
- 保持端口和协议一致：ERP MCP `8000/mcp`，Java `8080/api`，FastAPI `8090`，Vite `3000`。
- 新增或重命名 ERP MCP 工具时，同时检查 `agent/tools/mcp_client.py` 的前缀分组和 `subagents/configs/*.yaml` 的工具名。
- 修改订单写操作时保留 `interrupt_on` 人工审批，前端必须仍能处理 `interrupt` 和 resume 事件。
- 修改存储时区分三类状态：MongoDB checkpoint、`/memories/` StoreBackend、默认 OpenSandbox 文件系统。
- 修改 skills 时维持“只在需要时读取 SKILL.md”的渐进披露方式；不要把完整技能正文塞进系统提示词。
- `requirements.txt` 是主要锁定依赖集合，课程要求固定 `deepagents==0.4.12`；FastAPI 和 `langgraph-checkpoint-mongodb` 目前需要额外安装。不要无验证升级核心 Agent 依赖。
- `.env` 只保存本地密钥，禁止提交。现有远端服务地址应逐步环境变量化，文档或测试中不得新增真实凭据。
- `langgraph.json` 属于模板遗留配置；当前主入口是 FastAPI 的 graph factory。确认导出对象存在前，不要把 `langgraph dev` 写成默认启动方式。

## 启动与验证

```bash
# 安装 Python 依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install fastapi langgraph-checkpoint-mongodb

# ERP MCP（Java 服务必须已在 8080 运行）
PYTHONPATH=src python -m mcp_server.server_main

# FastAPI（另一个终端）
PYTHONPATH=src python -m uvicorn api_view.web_main:app --reload --host 0.0.0.0 --port 8090

# Vue（另一个终端）
cd frontend
npm ci
npm run dev
```

按改动范围验证：

```bash
PYTHONPATH=src pytest src/test
cd frontend && npm run build
```

测试包含对本地和远端服务的集成调用。失败时先区分环境不可达、凭据缺失和代码回归；不要为了让测试通过而删除集成断言或绕过 HITL/沙箱边界。
