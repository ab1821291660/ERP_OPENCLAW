# ERP结合多 Agent 项目技术解析文档
【稀土掘金-EMA-前端开发】ERP结合多 Agent 项目技术解析文档2026-06-13：：https://juejin.cn/post/7650416991426527273
将https://juejin.cn/post/7650416991426527273个文章下载为111.md，并保存到docs目录下
##
##
> 原文：[ERP结合多 Agent 项目技术解析文档](https://juejin.cn/post/7650416991426527273)
> 作者：EMA
> 发布于：2026-06-13

## ERP_OPENCLAW 多 Agent 项目技术解析文档

> 面向学习者的源码导读。重点解释：RAG/增强生成链路、智能体通信、MCP 应用、Skill 管理、状态管理，以及项目复杂点和亮点。

---

### 1. 项目总体定位

`ERP_OPENCLAW` 是一个围绕“摩托车零部件采购 ERP”的多 Agent 智能助手项目。它不是单纯的聊天机器人，而是把多个系统组合成一个业务型 Agent 应用：

- Python Agent 后端：基于 LangGraph、DeepAgents、LangChain、FastAPI。
- 多 Agent 编排：主 Agent 负责协调，采购分析 Agent 和订单 Agent 负责具体任务。
- MCP 工具层：把 Java ERP 后端 API 和远程可视化服务包装成 Agent 可调用工具。
- Skill 系统：用 `SKILL.md` + 脚本 + 数据文件组织可复用能力。
- 沙箱执行：用 OpenSandbox 执行脚本、读写报告、同步技能文件。
- 状态持久化：LangGraph checkpoint 用 MongoDB，用户偏好和技能用 StoreBackend 路由。
- 前端：Vue 3 + Vite，通过 SSE 展示流式 token、工具调用、人工中断。
- 业务后端：Java Spring Boot + MyBatis Plus + MySQL 的 ERP 示例系统。

可以把它理解为：

```text
用户
  -> Vue 前端
  -> FastAPI SSE 接口
  -> LangGraph / DeepAgents 主 Agent
  -> 子 Agent
  -> MCP 工具
  -> Java ERP / 可视化 MCP / Web Search / 沙箱 Skill
  -> 返回分析报告、图表、订单操作结果
```

---

### 2. 目录地图

核心目录如下：

```text
ERP_OPENCLAW/
  langgraph.json                         LangGraph 图入口配置
  start_web.py                           一键启动 FastAPI + Vue
  requirements.txt                       Python 实际依赖快照
  pyproject.toml                         LangGraph 模板依赖
  src/
    agent/                               多 Agent 核心
      main_agent.py                      Agent 初始化总入口
      config.py                          LLM、沙箱、MongoDB、Store 配置
      memory/                            主 Agent 系统提示词和 AGENTS.md
      middlewares/                       上下文、Skill、记忆、摘要中间件
      subagents/                         子 Agent YAML 加载器与配置
      tools/                             web_search、MCP client、HITL、图表合并等
      backends/                          OpenSandbox 后端适配
    mcp_server/                          本地 FastMCP 服务
      server_main.py                     MCP Server 入口
      tools/                             ERP API 工具封装
    api_view/                            FastAPI Web API
      api/chat.py                        SSE 流式对话和中断恢复
      api/history.py                     会话历史
      agent_loader.py                    Agent 单例与 MongoDB 展示消息
    skills/                              Skill 能力包
      main/skill-management/
      procurement/procurement-analysis/
      procurement/supplier-price-urls/
      procurement/web-scraper/
      procurement/web-content-fetcher/
  frontend/                              Vue 3 前端
  Java写的ERP项目(用于手撕OpenClaw项目)/
    MotorcyclePartsProcurementSystem/    Java ERP 后端
```

---

### 3. 核心技术栈

| 层级 | 技术 | 作用 |
| --- | --- | --- |
| Agent 编排 | LangGraph, DeepAgents | 构建可 checkpoint、可流式、可子 Agent 委派的智能体图 |
| LLM 接入 | LangChain ChatOpenAI, DeepSeek, Zhipu 兼容 OpenAI 接口 | 主模型、摘要模型、备用模型 |
| MCP | FastMCP, langchain-mcp-adapters, MultiServerMCPClient | 将外部服务暴露为工具并接入 LangChain |
| Web API | FastAPI, Uvicorn, SSE | 对前端提供流式聊天、恢复中断、历史接口 |
| 状态存储 | MongoDBSaver, MongoDB, InMemoryStore, StoreBackend, CompositeBackend | checkpoint、展示消息、用户记忆、技能持久化 |
| 沙箱 | OpenSandbox, 自定义 OpenSandboxBackend | 执行代码、同步 Skill、生成报告和图表 |
| 前端 | Vue 3, Vite, markdown-it, highlight.js, fetch stream | 聊天 UI、工具调用面板、HITL 中断交互 |
| 业务系统 | Spring Boot 3.1.10, Java 17, MyBatis Plus, MySQL | ERP 供应商、物料、订单、库存等 REST API |

注意：Java 子项目 README 写的是 Spring Boot 2.7.x / JDK 1.8，但 `pom.xml` 实际是 Spring Boot `3.1.10`、Java `17`，学习时以 POM 为准。

---

### 4. 启动与初始化链路

#### 4.1 服务启动

`start_web.py` 做两件事：

1. 启动 FastAPI：

```text
uvicorn api_view.web_main:app --reload --host 0.0.0.0 --port 8090
```

1. 等待 `/health` 就绪后启动 Vue：

```text
npm run dev
```

FastAPI 启动时会进入 `api_view/web_main.py` 的 lifespan，调用：

```python
await agent_loader.initialize()
```

`AgentLoader` 再懒加载 `agent.main_agent.get_agent_async()`。

#### 4.2 Agent 初始化 9 阶段

核心在 `src/agent/main_agent.py:create_main_agent()`：

1. 创建或连接 OpenSandbox。
2. 上传 `src/agent/memory/AGENTS.md` 到沙箱 `/AGENTS.md` 。
3. 构建 `CompositeBackend` ，把不同路径路由到不同后端。
4. 连接 MCP Server，加载 ERP 工具和可视化工具。
5. 将 26 类可视化 MCP 工具合并成 `generate_visualization` 。
6. 创建 `assign_skill` 、 `download_sandbox_file` 等本地工具。
7. 加载子 Agent YAML 配置。
8. 给主 Agent 和子 Agent 组装中间件。
9. 调用 `create_deep_agent(...)` 生成可运行图。

主 Agent 创建时传入的关键参数：

```python
create_deep_agent(
    model=MAIN_MODEL,
    system_prompt=system_prompt,
    skills=["/skills/main/"],
    memory=["/AGENTS.md"],
    tools=[web_search, assign_skill, download_sandbox_file],
    subagents=subagents,
    middleware=main_middleware,
    backend=backend,
    store=STORE,
    checkpointer=CHECKPOINTER,
    context_schema=ProcurementContext,
)
```

这说明主 Agent 本身只保留通用能力，ERP 业务操作主要靠子 Agent。

---

### 5. RAG 是怎么搭建的

#### 5.1 先说结论：不是传统向量库 RAG

源码中没有发现典型传统 RAG 组件：

- 没有 embedding 模型调用。
- 没有 FAISS、Chroma、Milvus、pgvector 等向量库。
- 没有 document splitter、retriever、reranker 链路。

所以这个项目的“RAG”更准确地说是“工具增强 + Skill 文档增强 + 记忆增强 + 文件系统增强”的 Agentic RAG。

它的增强来源不是向量检索，而是以下几类上下文：

| 增强来源 | 代码位置 | 作用 |
| --- | --- | --- |
| 全局操作手册 | `src/agent/memory/AGENTS.md` | 规定主 Agent 生命周期、委派规则、记忆规则、安全边界 |
| Skill 文档 | `src/skills/**/SKILL.md` | 子 Agent 按需读取专业流程说明 |
| 业务数据 | MCP ERP 工具 | 从 Java ERP 获取供应商、零部件、订单、库存 |
| 外部报价 | `supplier-price-urls` + `web-scraper` | 先查 URL 映射，再抓网页转 Markdown |
| Web 搜索 | `src/agent/tools/web_search.py` | 市场行情、供应商背景、通用知识 |
| 长期记忆 | `/memories/{user_id}/preferences.md` | 用户偏好、最近供应商、最近查询 |
| 沙箱文件 | `/analysis/report_*.md`, `/analysis/temp/*.md` | 分析报告、抓取页面、临时数据 |

#### 5.2 Agentic RAG 流程

以“帮我分析某零件供应商价格”为例：

```text
用户问题
  -> 主 Agent 读取 /memories/{user_id}/preferences.md
  -> 判断是采购分析任务
  -> task 委派 procurement-analyst
  -> procurement-analyst 读取 /skills/procurement/procurement-analysis/SKILL.md
  -> 调用 MCP 工具查 ERP 内部数据
  -> 读取 supplier-price-urls/data/url_mapping.yaml
  -> 命中 URL 后执行 web-scraper 抓取外部页面
  -> 运行 Python 分析脚本
  -> 调用 generate_visualization 生成图表
  -> 写 /analysis/report_xxx.md
  -> 返回报告路径、摘要、结论、建议
```

这类设计的核心思想是：让 Agent 自己按任务需要读取权威说明和调用工具，而不是提前把所有文档塞进向量库。

#### 5.3 优点与限制

优点：

- 对结构化业务系统更直接，ERP 数据直接从 API 来，不经过文本召回。
- Skill 是可读、可维护的操作手册，适合教学和迭代。
- 沙箱文件让大结果可 offload，不必全部塞进模型上下文。
- 用户记忆能跨轮保留偏好，使输出越来越个性化。

限制：

- 没有语义检索能力，无法在大量非结构化文档中按语义召回。
- 依赖 Agent 自觉按步骤读 Skill，提示词和工具描述质量很关键。
- URL 映射是静态 YAML，需要维护。
- RAG 质量依赖 MCP/API/网页抓取返回质量。

---

### 6. 智能体怎么通信

项目里有三层通信。

#### 6.1 前端与后端通信：SSE

前端 `frontend/src/api/chat.js` 用 `fetch + ReadableStream` 调用：

```text
POST /api/chat/stream
POST /api/chat/{thread_id}/resume
```

后端 `src/api_view/api/chat.py` 使用 `StreamingResponse` 持续推送 SSE：

```text
token         AI 文本片段
tool_start    工具开始调用
tool_args     工具参数流式片段
tool_result   工具执行结果
tool_end      工具结束
interrupt     人工介入中断
done          本轮结束
error         错误
```

前端把这些事件转换成消息列表、工具面板和中断横幅。

#### 6.2 前端、后端、Agent 的端到端通信链路

一次普通对话从前端输入框到 Agent 再回到 UI，大致分 8 步：

```text
1. App.vue 用户点击发送
   -> handleSend(message)

2. frontend/src/api/chat.js
   -> streamChat(message, threadId, callbacks, abortSignal)
   -> POST /api/chat/stream
   -> body: { message, thread_id }

3. src/api_view/api/chat.py
   -> chat_stream(request)
   -> thread_id = request.thread_id or uuid.uuid4()
   -> StreamingResponse(stream_chat_response(...))

4. stream_chat_response()
   -> context = {"user_id": "laoxiao", "username": "laoxiao"}
   -> config = agent_loader.create_config(thread_id)
   -> current_input = {"messages": [{"role": "user", "content": message}]}

5. AgentLoader
   -> agent_loader.agent 已在 FastAPI lifespan 中初始化
   -> 底层来自 agent.main_agent.get_agent_async()

6. LangGraph / DeepAgents
   -> agent_loader.agent.astream(
        input=current_input,
        config=config,
        context=context,
        stream_mode=["messages", "values"],
        subgraphs=True,
        version="v2",
      )

7. 后端把 LangGraph chunk 转成 SSE
   -> AI token: type=token
   -> 工具调用: type=tool_start/tool_args/tool_result/tool_end
   -> 中断: type=interrupt
   -> 完成: type=done

8. 前端 _processStream() 解析 SSE
   -> onToken 更新 assistant 消息
   -> onToolStart/onToolArgs/onToolResult 更新工具消息
   -> onInterrupt 显示 InterruptBanner
   -> onDone 更新 thread_id / 会话列表
```

这里有几个关键设计点：

| 设计点 | 代码位置 | 作用 |
| --- | --- | --- |
| `thread_id` | `frontend/src/App.vue`, `src/api_view/api/chat.py`, `AgentLoader.create_config()` | 同一个会话的 LangGraph checkpoint key |
| `context` | `stream_chat_response()` | 给 Agent 注入 `user_id`、`username`，后续由 `ContextInjectionMiddleware` 写入 system message |
| `stream_mode=["messages","values"]` | `agent_loader.agent.astream(...)` | `messages` 用于展示 token/工具，`values` 用于检测 interrupt |
| `subgraphs=True` | `agent_loader.agent.astream(...)` | 让子 Agent 的流式输出也能被后端捕获 |
| `source` | `extract_subagent_name(namespace)` | 标记消息来自 `main` 还是某个子 Agent |
| `display_messages` | `stream_chat_response()` + `AgentLoader.save_display_messages()` | 保存 UI 友好的消息顺序，包含工具和子 Agent 消息 |

后端并不是把 Agent 的原始状态直接丢给前端，而是在 `chat.py` 里做了一层“流事件适配”：

```text
LangGraph chunk
  -> 后端解析 token / metadata / namespace
  -> 转成统一 SSE JSON
  -> 前端按 type 更新 UI
```

这个适配层非常重要。LangGraph 的 checkpoint 更适合恢复执行，前端展示则需要“用户消息、助手文本、工具调用、工具结果”按时间顺序混排，所以项目额外维护了 `session_display_messages` 集合来保存展示消息。

#### 6.3 中断恢复通信：前端如何把人工输入送回 Agent

订单流程里有两种中断：

```text
order_info_supplement  缺字段，需要用户补充自然语言信息
hitl_approval          创建/修改订单前，需要用户 approve/reject
```

后端检测到中断时，会发送：

```json
{
  "type": "interrupt",
  "interrupt_type": "order_info_supplement",
  "missing_fields": "...",
  "collected_data": "...",
  "thread_id": "..."
}
```

或：

```json
{
  "type": "interrupt",
  "interrupt_type": "hitl_approval",
  "action_requests": [...],
  "review_configs": [...],
  "thread_id": "..."
}
```

前端 `InterruptBanner.vue` 根据 `interrupt_type` 展示不同 UI：

- `order_info_supplement` ：展示缺失字段和文本框，提交 `{ supplement: "..." }` 。
- `hitl_approval` ：展示待执行订单操作，提交 `{ decisions: [{ type: "approve" }] }` 或 reject。

恢复时链路如下：

```text
InterruptBanner.vue
  -> emit("resume", resumeData)
  -> App.vue handleResume(resumeData)
  -> frontend/src/api/chat.js resumeChat(threadId, resumeData)
  -> POST /api/chat/{thread_id}/resume
  -> chat.py chat_resume()
  -> stream_chat_response(thread_id=..., resume_data=...)
  -> current_input = Command(resume=resume_data)
  -> agent_loader.agent.astream(...) 继续原 checkpoint
```

这里 `thread_id` 很关键：恢复不是新开一轮普通对话，而是在同一个 checkpoint 上用 `Command(resume=...)` 继续执行被暂停的 LangGraph。

#### 6.4 后端和 Agent 的生命周期通信

FastAPI 后端启动时通过 lifespan 初始化 Agent：

```text
web_main.py lifespan
  -> agent_loader.initialize()
  -> MongoClient(MONGODB_URI)
  -> get_agent_async()
  -> create_main_agent()
```

`AgentLoader` 是后端与 Agent 之间的门面：

| 方法 | 作用 |
| --- | --- |
| `initialize()` | 初始化 MongoDB 连接并懒加载 Agent |
| `create_config(thread_id, user_id)` | 构造 LangGraph configurable，用于 checkpoint |
| `get_current_messages(thread_id)` | 从 Agent checkpoint 获取当前消息 |
| `get_state_history(thread_id)` | 获取 LangGraph 状态历史 |
| `save_display_messages(thread_id, messages)` | 保存前端展示消息 |
| `get_display_messages(thread_id)` | 读取前端展示消息 |
| `delete_session(thread_id)` | 删除 checkpoint 和展示消息 |

也就是说，后端和 Agent 的通信有两条线：

```text
执行线：FastAPI -> AgentLoader.agent.astream() -> LangGraph/DeepAgents
状态线：FastAPI -> AgentLoader -> MongoDB checkpoint/display_messages
```

#### 6.5 通信数据结构速记

| 方向 | 数据结构 | 示例 |
| --- | --- | --- |
| 前端到后端普通对话 | `{ message, thread_id }` | `POST /api/chat/stream` |
| 前端到后端恢复中断 | `{ resume: {...} }` | `POST /api/chat/{thread_id}/resume` |
| 后端到 Agent 普通输入 | `{"messages": [{"role": "user", "content": message}]}` | `current_input` |
| 后端到 Agent 恢复输入 | `Command(resume=resume_data)` | HITL 继续执行 |
| 后端到前端文本 | SSE `{type:"token", content, source}` | 流式文字 |
| 后端到前端工具 | SSE `{type:"tool_start/tool_args/tool_result/tool_end", ...}` | 工具面板 |
| 后端到前端中断 | SSE `{type:"interrupt", interrupt_type, ...}` | 人工介入 UI |
| 后端到前端完成 | SSE `{type:"done", thread_id, content, interrupted}` | 一轮结束 |

#### 6.6 主 Agent 与子 Agent 通信：DeepAgents task 工具

主 Agent 的 `system_prompt` 明确要求：

- 分析类任务委派 `procurement-analyst` 。
- 订单类任务委派 `procurement-order` 。
- 主 Agent 自己只处理问候、功能询问、通用搜索和技能管理。

委派通过 DeepAgents 内置的 `task` 工具完成。主 Agent 把任务目标、用户偏好、原始需求写入 `description`，子 Agent 根据自己的 YAML `system_prompt` 和工具列表执行。

子 Agent 配置在：

```text
src/agent/subagents/configs/procurement_analyst.yaml
src/agent/subagents/configs/procurement_order.yaml
```

加载器 `src/agent/subagents/loader.py` 会把 YAML 中的工具名模式匹配为真实工具对象。

#### 6.7 Agent 与外部系统通信：MCP 和工具调用

Agent 不直接访问 Java API，而是走 MCP：

```text
Agent
  -> MultiServerMCPClient
  -> FastMCP 本地 erp-api server
  -> httpx.AsyncClient
  -> Java ERP REST API
```

另外还连接远程魔塔 MCP：

```text
Agent -> ModelScope MCP -> generate_* 可视化工具
```

这让业务 API、可视化能力都变成 LangChain `StructuredTool`，统一纳入 Agent 的工具调用系统。

---

### 7. MCP 在里面的应用

#### 7.1 MCP Server 端

入口是 `src/mcp_server/server_main.py`：

```python
mcp = FastMCP(
    name="Java-Backend-MCP-Server",
    instructions="调用 Java 后端 REST API 的工具集，支持按业务分组访问",
    version="1.0.0",
    lifespan=mcp_lifespan,
)
```

它注册四类工具：

| 文件 | 工具前缀 | 说明 |
| --- | --- | --- |
| `suppliers_tools.py` | `supplier_` | 供应商查询 |
| `parts_tools.py` | `part_` | 零部件分页、搜索、按供应商查询 |
| `order_tools.py` | `order_` | 创建、更新、搜索订单明细 |
| `inventory_tools.py` | `inventory_` | 库存预警 |

`http_base.py` 在 MCP lifespan 中创建共享 `httpx.AsyncClient`：

```python
yield {"http_client": http_client}
```

每个工具再通过：

```python
ctx.request_context.lifespan_context.get("http_client")
```

复用连接池访问 Java 后端。

#### 7.2 MCP Client 端

入口是 `src/agent/tools/mcp_client.py`：

```python
MCP_SERVER_CONFIG = {
    "erp-api": {
        "url": "http://127.0.0.1:8000/mcp",
        "transport": "streamable_http",
    },
    "analysis": {
        "url": "https://mcp.api-inference.modelscope.net/af3893df5be041/mcp",
        "transport": "streamable_http",
    },
}
```

加载后按前缀分组：

- `supplier_` , `part_` , `inventory_` 给采购分析 Agent。
- `order_` 给订单 Agent。
- `generate_` 给图表工具合并器。

#### 7.3 可视化 MCP 的二次封装

`src/agent/tools/chart_generator.py` 把 26 个 `generate_*` 工具合并成一个：

```text
generate_visualization(chart_type, chart_config)
```

这样可以减少 Agent 工具列表长度，避免模型在 26 个相似工具里迷路。

它还把完整参数说明写入技能文件思路中：

```text
/skills/procurement/chart_params.md
```

子 Agent 不确定参数时先读取参考文件，再调用统一图表工具。

这是项目非常好的一个工程化亮点：工具太多时，用“统一入口 + 参数文档”降低上下文压力。

---

### 8. Skill 是怎么管理的

#### 8.1 Skill 的形态

Skill 通常是一个目录：

```text
skill-name/
  SKILL.md
  scripts 或 data 或 .py 文件
  _meta.json 可选
```

`SKILL.md` 包含 frontmatter：

```yaml
---
name: procurement-analysis
description: ...
---
```

正文是给 Agent 读的操作手册。这个项目的 Skill 不是普通文档，而是“可执行工作流说明”。

#### 8.2 预置 Skill 同步

`SkillsSyncMiddleware` 在每轮 Agent 运行前扫描本地：

```text
src/skills/
```

然后上传到沙箱：

```text
/skills/{scope}/...
```

它会计算文件 MD5，避免重复上传。

#### 8.3 动态 Skill 管理

主 Agent 有 `/skills/main/skill-management/` 技能，负责：

1. 下载 ZIP 技能包。
2. 解压到 `/skills/main/{name}/` 。
3. 校验 `SKILL.md` 。
4. 在沙箱内测试。
5. 调用 `assign_skill` 分配给目标 Agent。
6. 持久化到 StoreBackend。

对应工具是 `src/agent/tools/assign_skill.py`。

#### 8.4 Skill 分配与 scope

scope 映射在 `src/agent/config.py`：

```python
SCOPE_MAP = {
    "main": "main",
    "procurement-analyst": "procurement",
    "procurement-order": "order",
}
```

分配后路径类似：

```text
/skills/procurement/web-scraper/
/skills/order/xxx/
```

子 Agent YAML 中配置：

```yaml
skills:
  - /skills/procurement/
```

这意味着新增技能只要进入对应 scope，子 Agent 就能通过渐进式读取发现它。

#### 8.5 持久化与恢复

动态技能会写入 StoreBackend 的 `("skills",)` namespace。下一轮运行时：

```text
UserSkillsRestoreMiddleware
  -> 从 StoreBackend asearch(("skills",))
  -> 上传回沙箱 /skills/{scope}/{skill_name}/...
```

所以技能生命周期是：

```text
本地预置 Skill -> 沙箱
用户动态 Skill -> /skills/main -> assign_skill -> /skills/{scope}
                            -> StoreBackend 持久化
下一轮会话 -> StoreBackend 恢复到沙箱
```

---

### 9. 状态怎么管理

项目状态分成五类。

#### 9.1 对话 checkpoint

`src/agent/config.py` 使用：

```python
CHECKPOINTER = MongoDBSaver(...)
```

主 Agent 创建时传入：

```python
checkpointer=CHECKPOINTER
```

调用时使用 `thread_id`：

```python
config = {
    "configurable": {
        "thread_id": "...",
        "user_id": "laoxiao"
    }
}
```

LangGraph 通过 MongoDB 保存每轮状态快照，因此可以继续会话、恢复中断、查看状态历史。

#### 9.2 前端展示消息

LangGraph checkpoint 中的消息不一定适合直接展示，尤其子 Agent 和工具结果容易丢失顺序。因此 `AgentLoader` 额外使用 MongoDB 集合：

```text
session_display_messages
```

并且逐条消息保存，避免 MongoDB 单文档 16MB 限制。

这是一个很实用的工程处理：checkpoint 用于恢复执行，display messages 用于 UI 展示。

#### 9.3 用户长期记忆

路径：

```text
/memories/{user_id}/preferences.md
```

由 `CompositeBackend` 路由到 `StoreBackend`：

```python
"/memories/": StoreBackend(
    runtime=rt,
    namespace=lambda rt: (getattr(rt.runtime.context, "user_id", "laoxiao"),),
)
```

内容包括：

```yaml
preferred_output: chart
preferred_chart_type: bar
preferred_currency: CNY
preferred_language: zh
recent_suppliers: []
recent_queries: []
```

`ContextInjectionMiddleware` 会把用户 ID、用户名、偏好文件路径注入 system message。

`MemoryUpdateMiddleware` 在每轮 Agent 完成后自动提取供应商和查询摘要，更新 `recent_suppliers`、`recent_queries`。

#### 9.4 Skill 持久化状态

路径：

```text
/persisted-skills/
```

同样由 `CompositeBackend` 路由到 `StoreBackend`，namespace 是：

```python
SKILLS_STORE_NAMESPACE = ("skills",)
```

动态技能不会只留在当前沙箱里，而是持久化到 Store，后续由 `UserSkillsRestoreMiddleware` 恢复。

#### 9.5 Human-in-the-Loop 中断状态

订单 Agent 有两层中断：

1. 数据不完整时，调用 `request_order_info()` 。
2. 执行 `order_create` / `order_update` 前， `interrupt_on` 触发人工审批。

`request_order_info` 使用：

```python
interrupt({
    "type": "order_info_request",
    "missing_fields": missing_fields,
    "collected_data": collected_data,
})
```

审批配置在 `procurement_order.yaml`：

```yaml
interrupt_on:
  order_create:
    allowed_decisions: ["approve", "reject"]
  order_update:
    allowed_decisions: ["approve", "reject"]
```

FastAPI 检测到中断后返回 SSE `interrupt` 事件，前端展示 `InterruptBanner`。用户补充或审批后调用：

```text
POST /api/chat/{thread_id}/resume
```

后端用：

```python
Command(resume=resume_data)
```

恢复 LangGraph 执行。

---

### 10. 业务流程拆解

#### 10.1 采购分析流程

```text
用户提出分析需求
  -> 主 Agent 判断为分析类任务
  -> 委派 procurement-analyst
  -> 子 Agent 扫描 /skills/procurement/
  -> 读取 procurement-analysis/SKILL.md
  -> 调 ERP MCP 查内部数据
  -> 读取 supplier-price-urls 映射
  -> web-scraper 抓外部报价
  -> Python 脚本分析
  -> generate_visualization 生成图表
  -> 写 /analysis/report_xxx.md
  -> 返回摘要和建议
```

适合学习点：

- 如何用 Skill 固化分析流程。
- 如何组合 ERP 结构化数据和外部网页数据。
- 如何把多图表 MCP 工具压缩成统一工具。
- 如何让子 Agent 产出文件而不是把大 JSON 塞回对话。

#### 10.2 采购订单流程

```text
用户提出创建/修改订单
  -> 主 Agent 委派 procurement-order
  -> 子 Agent 提取订单字段
  -> Schema 校验
  -> 缺字段则 request_order_info 中断
  -> 用户补充后 resume
  -> 调用 order_create/order_update 前 HITL 审批
  -> 用户 approve/reject
  -> approve 后 MCP 调 Java ERP API
  -> 返回操作结果
```

适合学习点：

- 如何在 Agent 中做关键操作审批。
- 如何用自然语言补全结构化字段。
- 如何把危险业务操作限制在专门子 Agent 内。

---

### 11. 复杂点与亮点统计

#### 11.1 架构复杂点

| 编号 | 复杂点 | 说明 |
| --- | --- | --- |
| 1 | 多系统组合 | Python Agent、Vue 前端、MCP Server、Java ERP、MongoDB、OpenSandbox 同时工作 |
| 2 | 多 Agent 委派 | 主 Agent 只做协调，子 Agent 根据 YAML 动态加载工具和技能 |
| 3 | MCP 双来源 | 同时接本地 ERP MCP 和远程可视化 MCP |
| 4 | 状态分层 | checkpoint、展示消息、用户记忆、技能持久化、沙箱文件分别管理 |
| 5 | HITL 恢复 | 需要前端、FastAPI、LangGraph checkpoint、Command resume 协同 |
| 6 | 沙箱与 Store 路由 | `CompositeBackend` 把 `/memories/`、`/persisted-skills/` 和普通文件分流 |
| 7 | Skill 生命周期 | 预置同步、动态下载、测试、分配、持久化、恢复 |
| 8 | 工具结果展示 | SSE 中要区分 token、tool call、tool result、子 Agent source |
| 9 | 长上下文控制 | DeepAgents offloading + summarization + 主动 compact |
| 10 | 业务安全 | 订单创建/更新必须数据补齐和人工审批 |

#### 11.2 工程亮点

- `create_main_agent()` 的初始化分阶段很清晰，是学习 Agent 工程启动链路的好入口。
- 子 Agent 用 YAML 配置，提示词、工具、技能路径、HITL 配置都可外置。
- MCP 工具按前缀分组，能把不同能力分配给不同子 Agent。
- `generate_visualization` 把 26 个图表工具合并成一个统一入口，显著降低工具选择复杂度。
- `CompositeBackend` 路由设计很漂亮：沙箱负责临时执行，StoreBackend 负责记忆和技能持久化。
- `MemoryUpdateMiddleware` 自动维护最近供应商和查询摘要，减少对 Agent 自觉性的依赖。
- `session_display_messages` 单独保存 UI 消息，避免直接依赖 checkpoint 展示。
- 订单流程实现了两类人工介入：信息补充和最终审批，适合真实业务系统。
- Skill 采用 `SKILL.md + 脚本 + 数据` ，让 Agent 能力可文档化、可迁移、可扩展。

#### 11.3 当前风险与可改进点

- `src/mcp_server/tools/suppliers_tools.py` 中 `supplier_query` 使用了未定义的 `request_params` ，运行时大概率会报错，应改为 `{"name": name}` 。
- `src/agent/config.py` 和 `src/api_view/web_config.py` 中包含硬编码 MongoDB、OpenSandbox、模型服务地址和密码，生产环境应改为环境变量。
- `STORE = InMemoryStore()` 会导致用户记忆和技能持久化只在进程内有效；若要跨进程/重启持久化，应换成 Redis/Mongo/Postgres 等持久 Store。
- `README.md` 仍是 LangGraph 模板说明，未描述真实项目。
- Java README 与 POM 版本不一致，容易误导部署。
- `requirements.txt` 中有 `-e e:\my_project\project30` 这种本机路径，迁移环境可能失败。
- 测试文件偏手动验证，缺少自动化集成测试覆盖 MCP 工具、Agent 委派、HITL resume。
- MCP 工具错误返回多为字符串，不够结构化，Agent 解析时容易不稳定。

---

### 12. 推荐学习路线

按这个顺序读源码会比较顺：

1. `langgraph.json`
2. `start_web.py`
3. `src/api_view/web_main.py`
4. `src/api_view/agent_loader.py`
5. `src/agent/main_agent.py`
6. `src/agent/config.py`
7. `src/agent/memory/prompts.py`
8. `src/agent/memory/AGENTS.md`
9. `src/agent/subagents/configs/*.yaml`
10. `src/agent/subagents/loader.py`
11. `src/agent/tools/mcp_client.py`
12. `src/mcp_server/server_main.py`
13. `src/mcp_server/tools/*.py`
14. `src/agent/middlewares/*.py`
15. `src/skills/**/SKILL.md`
16. `src/api_view/api/chat.py`
17. `frontend/src/api/chat.js`
18. `frontend/src/App.vue`
19. Java ERP 的 `pom.xml` 、 `application.yml` 、controller/service/mapper

---

### 13. 五个重点问题速答

#### RAG 怎么搭建？

没有传统向量库 RAG。项目采用 Agentic RAG：通过 `AGENTS.md`、Skill 手册、MCP 工具、Web Search、网页抓取、用户记忆和沙箱文件来增强生成。

#### 智能体怎么通信？

前端和后端通过 SSE 通信；主 Agent 和子 Agent 通过 DeepAgents `task` 工具委派；Agent 和外部系统通过 MCP 工具通信；中断恢复通过 LangGraph `Command(resume=...)`。

#### MCP 怎么应用？

本地 FastMCP 把 Java ERP REST API 包装成 `supplier_`、`part_`、`order_`、`inventory_` 工具；Agent 端用 `MultiServerMCPClient` 加载；远程 ModelScope MCP 提供可视化工具。

#### Skill 怎么管理？

预置 Skill 从 `src/skills` 同步到沙箱；动态 Skill 先放 `/skills/main`，测试后用 `assign_skill` 分配到 `/skills/{scope}`，再写入 StoreBackend，下次会话恢复。

#### 状态怎么管理？

LangGraph checkpoint 用 MongoDB；前端展示消息单独存 MongoDB；用户偏好走 `/memories/{user_id}` StoreBackend；技能走 `/persisted-skills` StoreBackend；临时报告和脚本结果放 OpenSandbox 文件系统。

---

### 14. 一句话总结

这个项目的核心价值不在“某个单点算法”，而在把多 Agent、MCP、Skill、沙箱、业务 API、记忆、HITL 和前端流式交互拼成了一个完整业务闭环。学习它时，建议重点看“能力如何被封装成工具和 Skill、状态如何跨轮保存、主 Agent 如何把复杂任务安全地委派出去”。

