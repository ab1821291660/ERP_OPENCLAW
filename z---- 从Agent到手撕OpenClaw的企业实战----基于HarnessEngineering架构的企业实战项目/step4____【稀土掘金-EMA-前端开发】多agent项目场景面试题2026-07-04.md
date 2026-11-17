# 多agent项目场景面试题
【稀土掘金-EMA-前端开发】多agent项目场景面试题2026-07-04::https://juejin.cn/post/7658236929163280393
将https://juejin.cn/post/7658236929163280393这个文章下载为aaa.md，并保存到docs目录下
##
##
> 原文：[多agent项目场景面试题](https://juejin.cn/post/7658236929163280393)
> 作者：EMA
> 发布于：2026-07-03


## ERP_OPENCLAW AI Agent 项目面试准备
> 适用场景：AI 应用开发、Agent 工程化、MCP 工具调用、业务系统智能化、企业级流程自动化方向面试。
>
> 回答风格：不要只讲概念，要把“业务痛点、最初方案、遇到的问题、后来怎么改、效果提升”讲出来。

### 一、自我介绍里的项目描述

我做过一个面向摩托车零部件采购 ERP 的多 Agent 智能助手项目，项目名字叫 `ERP_OPENCLAW`。它不是一个简单的聊天机器人，而是把一个 Java Spring Boot + MyBatis Plus + MySQL 的采购 ERP 系统，改造成可以被 AI Agent 调用和协同处理的业务系统。

这个 ERP 本身包含供应商、零部件、采购订单、库存、客户、物流、统计分析等模块。传统使用方式里，采购人员要自己去查供应商、查物料、查历史订单、看库存预警，再去外部网页找报价，最后人工整理成采购分析报告或创建订单。痛点是流程长、跨系统操作多、字段容易漏、分析结论依赖人工经验，而且订单创建这种动作风险高，不能让模型直接乱调接口。

所以我在这个项目里做了一层 Agent 工程化改造：用 LangGraph / DeepAgents 做主 Agent 和子 Agent 编排；用 MCP 把 Java ERP 的供应商、物料、订单、库存 API 包装成工具；用 Skill 系统把采购分析流程、网页抓取、供应商 URL 映射、图表参数说明沉淀成可复用能力；用 OpenSandbox 执行脚本和生成报告；用 MongoDB checkpoint 保存对话和中断状态；前端用 Vue + SSE 展示流式回答、工具调用和人工审批。

项目最终形成了两个核心业务闭环：

1. 采购分析闭环：用户说“帮我分析火花塞供应商价格”，主 Agent 会委派给采购分析子 Agent，子 Agent 调 ERP MCP 查内部供应商、零件、历史订单和库存，再结合 Skill 抓外部报价，最后生成图表和 Markdown 报告。
2. 采购订单闭环：用户说“帮我下一个 100 个博世火花塞的采购单”，订单子 Agent 会先抽取字段，缺少物料 ID、数量、单价等信息时触发人工补充，中间状态通过 LangGraph checkpoint 暂停；数据齐全后，调用 `order_create` 前还会触发人工审批，用户确认后才真正写入 ERP。

这个项目对我最大的价值是，它让我把 Agent 从“能聊天”推进到“能接真实业务系统、能分工、能中断、能审计、能生成交付物”的工程化形态。

### 二、项目痛点与提升点

#### 业务痛点

- 采购信息分散：供应商、物料、库存、订单、外部报价分散在 ERP 和网页里，人工查询成本高。
- 分析依赖人工经验：采购人员要自己比价、算价差、看库存、做供应商评分，报告产出慢。
- 订单操作风险高：采购单创建/修改涉及金额和库存，不能让 AI 直接调用接口。
- 自然语言到结构化字段有断层：用户说“买 100 个博世火花塞”，但接口需要 `partId`、`quantity`、`unitPrice`、交期等字段。
- 工具结果太长：ERP 查询、网页抓取、图表返回可能很大，直接塞进上下文会爆窗口。
- 多轮任务难恢复：订单创建中途缺字段或等待审批，如果页面刷新或会话中断，流程容易丢。
- 前端不可解释：如果只显示最终答案，用户不知道 Agent 调了哪些工具、查了哪些数据。

#### 改造后的提升点

- 从人工查数变成 Agentic RAG：不做传统向量库，而是让 Agent 按需读 Skill、调 MCP、抓网页、查 ERP。
- 从单 Agent 变成专业分工：主 Agent 只负责协调，采购分析交给 `procurement-analyst`，订单操作交给 `procurement-order`。
- 从直接调接口变成 MCP 工具层：Java ERP API 被包装成 `supplier_`、`part_`、`order_`、`inventory_` 工具，Agent 只通过工具访问业务系统。
- 从不可控操作变成 HITL 审批：订单创建/修改前必须人工 approve，缺字段时先触发 `request_order_info` 补充。
- 从一次性回答变成交付物：分析类任务会生成 `/analysis/report_xxx.md`，并可调用图表 MCP 生成可视化。
- 从黑盒执行变成可观察流式过程：前端展示 token、工具开始、工具参数、工具结果、子 Agent 来源和中断状态。
- 从会话临时状态变成可恢复状态：LangGraph checkpoint + MongoDB 支持同一 `thread_id` 下恢复中断。
- 从提示词堆叠变成 Skill 管理：采购分析流程、抓取脚本、URL 映射、图表参数都沉淀为 `SKILL.md + scripts + data`。

### 三、面试题与回答示范

#### 1. 你怎么向面试官解释这个项目的整体架构？

考察点：能否把复杂系统讲清楚。

回答示范：

我会把它拆成四层：第一层是原来的 Java ERP，负责供应商、物料、订单、库存这些真实业务数据；第二层是 MCP Server，把 Java REST API 包装成 Agent 可调用的工具；第三层是 Python Agent 层，用 LangGraph / DeepAgents 做主 Agent、采购分析子 Agent 和订单子 Agent；第四层是 Vue 前端，通过 SSE 展示流式回答、工具调用和人工审批。这样讲面试官比较容易理解：ERP 是业务底座，MCP 是工具适配层，Agent 是决策和编排层，前端是交互和可观测层。

#### 2. 为什么不是让一个 Agent 直接处理所有采购任务，而要拆主 Agent 和子 Agent？

考察点：多 Agent 边界设计。

回答示范：

一开始如果所有工具都塞给一个 Agent，它既能查供应商，又能创建订单，又能生成图表，工具列表很长，模型很容易选错工具，尤其订单操作风险比较高。后来我把主 Agent 定位成协调者，只处理意图识别、用户偏好、任务委派；分析类任务交给 `procurement-analyst`，订单类任务交给 `procurement-order`。这样分析 Agent 可以拥有更多查询和图表工具，订单 Agent 则限制工具数量，并加 HITL 审批，边界更安全。

#### 3. 这个项目里的 RAG 为什么说是 Agentic RAG，而不是传统向量库 RAG？

考察点：RAG 形态理解和业务适配。

回答示范：

这个项目没有 FAISS、Chroma、pgvector，也没有提前 embedding 文档。它的增强来源主要是 `AGENTS.md`、采购 Skill、ERP MCP 工具、外部网页抓取、用户记忆和沙箱文件。比如用户问火花塞供应商价格，Agent 不是去向量库召回一段文本，而是主动调用 `supplier_query`、`part_search`、`order_search_details`，再根据 `supplier-price-urls` 找外部报价页面抓取。对 ERP 这种结构化业务系统来说，直接调 API 比把数据转成文本再检索更可靠。

#### 4. MCP 在这个项目里解决了什么问题？

考察点：MCP 工具化和业务系统集成。

回答示范：

MCP 解决的是“Agent 怎么安全、统一地访问外部业务系统”。原来的 Java ERP 有很多 REST API，如果让 Agent 直接拼 HTTP 请求，参数、错误处理、鉴权都会散。项目里用 FastMCP 把供应商、物料、订单、库存 API 包装成 `supplier_`、`part_`、`order_`、`inventory_` 工具，Agent 端再通过 `MultiServerMCPClient` 加载。这样模型看到的是结构化工具，而不是一堆 URL。

#### 5. 采购分析 Agent 是怎么完成一份分析报告的？

考察点：Agent 工作流、工具调用、交付物生成。

回答示范：

以“分析火花塞供应商价格”为例，主 Agent 识别到这是分析类任务后，用 `task` 委派给 `procurement-analyst`。分析子 Agent 启动后先扫描 `/skills/procurement/`，读取 `procurement-analysis/SKILL.md`，然后按流程查 ERP 内部数据：供应商、零件、历史订单、库存预警；再读取 URL 映射，调用 web-scraper 抓外部报价；之后在沙箱里跑 Python 分析脚本，调用 `generate_visualization` 生成图表，最后写 `/analysis/report_xxx.md`。这比单纯让模型总结更像真实采购分析流程。

#### 6. 为什么要把 26 个图表 MCP 工具合并成一个 `generate_visualization`？

考察点：工具数量控制、上下文压缩、模型易用性。

回答示范：

可视化 MCP 原本有很多 `generate_*` 工具，如果全部暴露给 Agent，模型会在几十个类似工具里选择，工具描述也会占很多上下文。后来把它们封装成一个统一工具 `generate_visualization(chart_type, chart_config)`，具体柱状图、折线图、雷达图靠 `chart_type` 路由。参数说明放到 `/skills/procurement/chart_params.md`，Agent 需要时读一次就行。这个改动降低了工具选择复杂度，也节省了上下文。

#### 7. 订单创建为什么需要两层 Human-in-the-Loop？

考察点：业务安全和人工介入设计。

回答示范：

订单操作不是普通问答，涉及金额和库存，所以我设计了两层 HITL。第一层是数据补充：如果用户说“帮我买 100 个博世火花塞”，但缺 `partId`、单价、交期，订单 Agent 会调用 `request_order_info` 暂停，让用户补充自然语言信息。第二层是最终审批：数据齐全后，调用 `order_create` 或 `order_update` 前还会触发 `interrupt_on`，前端展示订单明细，用户点击同意才真正执行。这样既能让 AI 自动整理字段，又不会让它直接写业务数据。

#### 8. 中断后前端如何恢复同一个 Agent 流程？

考察点：LangGraph checkpoint、thread_id、Command resume。

回答示范：

关键是不要把补充信息当作一轮新聊天，而是恢复原来的 checkpoint。项目里每个会话都有 `thread_id`，当后端检测到 interrupt，会通过 SSE 发给前端，并保存展示消息。用户在 `InterruptBanner` 里补充信息或点击 approve 后，前端调用 `POST /api/chat/{thread_id}/resume`，后端用 `Command(resume=resume_data)` 继续执行原来的 LangGraph 状态。这样订单流程不会从头开始，也不会丢之前已经抽取的字段。

#### 9. 前端为什么要展示工具调用，而不是只展示最终答案？

考察点：Agent 可解释性、业务信任。

回答示范：

采购场景里，用户很关心“这个结论从哪来”。如果 Agent 说“建议选 DENSO”，但不展示它查了哪些供应商、哪些历史订单、哪些外部报价，用户很难信任。项目里后端把工具调用拆成 `tool_start`、`tool_args`、`tool_result`、`tool_end` 事件，前端 `ToolCallPanel` 展示工具名、参数、结果和来源。这样用户能看到 Agent 查了 ERP、抓了网页、生成了图表，整个过程更透明。

#### 10. 为什么要单独保存 display messages，而不是直接展示 LangGraph checkpoint？

考察点：状态存储分层。

回答示范：

LangGraph checkpoint 更适合恢复执行，但不一定适合前端展示。比如子 Agent 的工具调用、工具参数流、工具结果和最终 token 在 checkpoint 里不一定是 UI 需要的顺序。项目里 `AgentLoader` 额外保存 `session_display_messages`，把用户消息、助手 token、工具调用、工具结果按前端友好的结构存 MongoDB。这样 checkpoint 管执行恢复，display messages 管 UI 展示，职责分开。

#### 11. Skill 系统在这个项目里起什么作用？

考察点：可复用能力沉淀。

回答示范：

Skill 不是普通文档，而是给 Agent 读的操作手册和执行资源。比如 `procurement-analysis/SKILL.md` 定义分析流程，`supplier-price-urls` 存 URL 映射，`web-scraper` 里有抓网页脚本。采购分析 Agent 不需要把所有步骤写死在系统提示词里，而是在任务开始时扫描 `/skills/procurement/`，按需读取 Skill。这样后续新增一个“供应商信用评分”技能，不需要改 Agent 主代码，只要加 Skill 包即可。

#### 12. 动态 Skill 为什么需要持久化和恢复？

考察点：Agent 能力生命周期。

回答示范：

如果用户安装或分配了一个新 Skill，只存在沙箱里，重启后就丢了。项目里用 `assign_skill` 把动态 Skill 分配到对应 scope，比如 `/skills/procurement/`，再写入 StoreBackend 的 skills namespace。下一轮会话时 `UserSkillsRestoreMiddleware` 会从 Store 里恢复到沙箱。这个设计让 Agent 能力不是一次性的，而是可以跨会话保留。

#### 13. 用户偏好是怎么影响 Agent 输出的？

考察点：长期记忆和上下文注入。

回答示范：

项目里给每个用户维护 `/memories/{user_id}/preferences.md`，里面有偏好输出形式、图表类型、货币、语言、最近供应商和最近查询。`ContextInjectionMiddleware` 会把用户 ID、用户名和偏好路径注入 system prompt。比如用户说“以后都用表格”，主 Agent 会更新偏好文件；下次分析任务委派给子 Agent 时，description 里会带上用户偏好，报告自然会按表格或图表输出。

#### 14. 工具结果太长时怎么避免上下文爆掉？

考察点：长上下文治理、offloading、摘要。

回答示范：

采购分析经常会查很多订单明细、抓网页报价、生成图表，如果把原始 JSON 都塞回对话，很容易爆上下文。项目里借助 DeepAgents 的自动 offloading，大工具结果超过阈值会写入文件系统，上下文里只保留路径和预览；同时有 tools summarization middleware，在上下文接近窗口时生成摘要。分析 Agent 的 Skill 也明确要求最终只返回报告路径、摘要、结论和建议，不返回原始工具输出。

#### 15. 如果用户让 Agent 创建采购单，但缺少物料 ID，你怎么处理？

考察点：自然语言到结构化字段、信息补全。

回答示范：

我不会让模型猜物料 ID。订单 Agent 会先从自然语言里抽取供应商、产品、数量、单价等字段，然后对照 `order_create` schema 做校验。如果 `partId` 缺失，会调用 `request_order_info(missing_fields, collected_data)` 暂停，前端展示“缺少物料 ID”等信息。用户可以用自然语言补充，比如“物料ID=100，单价 25.5 元”，恢复后 Agent 解析并重新校验，直到字段齐全才进入审批。

#### 16. 这个项目怎么保证订单操作不被模型误执行？

考察点：安全边界和权限思维。

回答示范：

主要有三层控制。第一层是职责隔离：主 Agent 不直接调用订单 MCP 工具，订单操作必须委派给 `procurement-order`。第二层是 schema 校验和缺字段补充，数据不完整不能进入工具调用。第三层是 `interrupt_on` 审批，`order_create` 和 `order_update` 执行前必须暂停，前端展示订单明细，用户 approve 后才执行。如果用户 reject，就不会调用 Java ERP API。

#### 17. 如果 MCP 工具返回错误，Agent 怎么处理比较合理？

考察点：工具错误处理和用户体验。

回答示范：

我会让工具返回结构化错误，Agent 根据错误类型决定是否重试、补充信息或直接告知用户。项目里订单工具现在会返回 `{"error": "..."}`，子 Agent 的提示词要求失败时提取具体错误，不要重试超过 2 次。实际业务里，比如 ERP 返回物料不存在，就不应该盲目重试，而应该告诉用户“物料 ID 不存在，是否按名称重新搜索”；如果是临时网络错误，才适合重试。

#### 18. 这个项目有哪些工程风险，你会怎么改？

考察点：能否发现真实项目问题。

回答示范：

我会优先改三类。第一类是配置安全，项目里 MongoDB、OpenSandbox、模型服务地址和密码有硬编码，应该统一改成环境变量。第二类是持久化，当前 `STORE = InMemoryStore()`，用户记忆和动态 Skill 跨进程不稳，应该换成 MongoDB 或 Redis Store。第三类是工具健壮性，比如 supplier 工具里有未定义变量风险，MCP 工具返回也需要统一错误 schema。除此之外，README 还是模板说明，也需要更新成真实项目文档。

#### 19. 如果要把这个项目从演示版做成生产版，优先做什么？

考察点：工程化落地优先级。

回答示范：

我会优先做四件事：第一，配置和密钥治理，所有敏感信息环境变量化；第二，用户和权限体系，区分采购员、仓管、管理员，订单审批要有权限；第三，工具审计日志，记录每次 Agent 调了哪个 MCP 工具、参数是什么、结果是什么；第四，自动化测试，覆盖 MCP 工具、子 Agent 委派、HITL resume 和订单创建流程。因为这个项目已经能跑通业务闭环，生产化重点不是再加功能，而是安全、可追溯和稳定。

#### 20. 这个项目最能体现你 Agent 工程能力的地方是什么？

考察点：项目总结和个人亮点表达。

回答示范：

我觉得最能体现的是把 Agent 做成了一个业务闭环，而不是聊天 demo。这个项目里有主 Agent 和子 Agent 分工，有 MCP 工具接真实 ERP，有 Skill 沉淀采购分析流程，有沙箱执行脚本和生成报告，有 MongoDB checkpoint 恢复中断，还有前端展示工具调用和人工审批。尤其订单流程里，自然语言抽字段、缺字段中断、人工审批、再恢复执行，这一套比较接近真实企业系统对 AI Agent 的要求：能自动化，但不能失控。

### 四、快速复习关键词

- 整体架构：Vue 前端 + FastAPI SSE + LangGraph/DeepAgents + MCP + Java ERP + MongoDB + OpenSandbox。
- 业务痛点：跨系统查数、人工比价、字段缺失、订单风险、报告产出慢。
- Agent 分工：主 Agent 协调；`procurement-analyst` 做分析；`procurement-order` 做订单。
- MCP 工具：`supplier_`、`part_`、`order_`、`inventory_`。
- Agentic RAG：Skill + ERP API + 外部网页 + 用户记忆 + 沙箱文件。
- HITL：`request_order_info` 补字段；`interrupt_on` 审批订单操作。
- 状态管理：`thread_id`、MongoDB checkpoint、display messages、StoreBackend、沙箱文件。
- 可观测性：SSE 事件、工具调用面板、debug log、工具 source。
- 工程化提升：工具统一入口、Skill 持久化、上下文 offloading、报告文件化。
