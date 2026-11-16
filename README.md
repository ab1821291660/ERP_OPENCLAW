



【【多例--per-use沙箱与用户绑定】】 chat的stream_chat_response----调用agent_loader的get_agent_for_user获取/创建用户沙箱

预热沙箱：：可n个

每次请求基于 per-user 沙箱轻量创建 agent graph，实现用户级沙箱隔离。##===================================##===================================

码士 Harness 多智能体采购课程 --官网马：https://www.mashibing.com/course/2959 ----
Langfuse 智能体评估课程
公开 Harness 课程视频：：https://www.bilibili.com/video/BV1Cs7h6MEsX/?vd_source=56544f773befbd3fb9a51b0e1c98614c&spm_id_from=333.788.player.switch&p=7  
公开财务分析与评估视频：：https://www.bilibili.com/video/BV1aZub6bE3W/?vd_source=56544f773befbd3fb9a51b0e1c98614c&spm_id_from=333.788.videopod.episodes&p=7  



核心能力
Multi-Agent 编排：主 Agent 识别意图，将业务数据分析委派给 procurement-analyst，将订单查询和写操作委派给 procurement-order。
真实 ERP 数据：通过本地 FastMCP 服务调用 Java ERP 的供应商、零部件、库存和采购订单 API。
采购分析：结合 ERP 数据、供应商报价页、网络搜索与魔塔可视化 MCP，生成对比报告和图表。
订单闭环：支持订单数据补充、创建和更新；写操作在执行前触发 Human-in-the-Loop 审批。
Harness Engineering：通过技能渐进披露、上下文注入、工具结果摘要、调用限制、沙箱健康检查和熔断机制约束 Agent 行为。
用户隔离与记忆：每个用户使用独立 OpenSandbox；MongoDB 保存 checkpoint，CompositeBackend 将用户记忆和持久技能路由到 StoreBackend。##===================================##===================================
流式交互：FastAPI 通过 SSE 返回 token、工具调用、工具结果、中断与完成事件，Vue 前端实时展示并支持中断恢复。



##===================================##===================================
##===================================##===================================
##===================================##===================================
##===================================##===================================
# ERP OpenClaw
基于 LangGraph、DeepAgents、FastAPI、MCP 和 Vue 3 的 ERP 采购智能助手。
## 运行环境
- Python 3.10+（推荐 3.11）
- Node.js 18+
- MongoDB 6+（由你本地自行启动）##===================================
- Java ERP API，默认 `http://localhost:8080/api` ##===================================
- OpenSandbox，默认 `http://localhost:8081` ##===================================
## 初始化----安装Python与前端依赖
```bash
cd ERP_OPENCLAW

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install fastapi langgraph-checkpoint-mongodb

cd frontend
npm ci
cd ..
```
```bash
python3.11 -m venv .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
cd frontend && npm ci ##===================================
```
在 `.env` 中填写模型和 OpenSandbox 凭据。不要提交 `.env`。
本地开发默认 `PREWARM_SANDBOX=false`，启动 Python 服务时不会主动创建沙箱；
设置为 `true` 后才会在启动阶段预热一个沙箱。
`CLEANUP_SANDBOX_ON_SHUTDOWN=false` 会在服务重启时保留用户远程沙箱；
只有明确需要关机清理远程资源时才设为 `true`。


## 环境检查scripts/check_environment.py：
```bash
.venv/bin/python scripts/check_environment.py
```


## 启动
各服务手动启动，便于直接查看日志和处理端口占用。启动顺序：
1. 启动 MongoDB Docker 容器。
2. 启动 Java ERP API。
3. 启动 OpenSandbox（需要沙箱功能时）。
4. 启动 ERP MCP。
5. 
5. 启动 FastAPI 后端。
6. 启动 Vue 前端。

后三个服务分别在独立终端运行：
```bash
# 终端 1：ERP MCP
make mcp

# 终端 2：FastAPI 后端
make backend

# 终端 3：Vue 前端
make frontend
```
访问地址：
- 前端：http://localhost:3000
- API 文档：http://localhost:8090/docs
- MCP：http://127.0.0.1:8000/mcp
## 常用命令
```bash
make install
make check
make test
make lint
```
外部图表 MCP 是可选能力。仅在 `.env` 配置 `ANALYSIS_MCP_URL` 时加载，不配置不影响 ERP 基础工具。
## 开发与验证
```bash
# Python 测试；部分用例要求本地或远端依赖已启动
cd ERP_OPENCLAW
PYTHONPATH=src pytest src/test

# Vue前端生产构建
cd ERP_OPENCLAW/frontend
npm run build

# Java
cd motorcycle-parts-procurement-system
mvn test
```



## 一次请求如何执行【见api链路.jpg】：：链路Vue`:3000` → FastAPI`:8090` → Agent → ERP MCP`:8000` → Java`:8080
```text
Vue :3000
  -> FastAPI :8090
  -> ERP OPENCLAW主Agent
     -> procurement-analyst / procurement-order
     -> ERP MCP :8000/mcp
        -> Java ERP :8080/api
           -> MySQL motorparts_db
```
```text
Vue :3000 ──/api + SSE──▶ FastAPI :8090
                            │  为每个用户获取/创建独立 OpenSandbox，##===================================##===================================
                            │  再用 graph factory 轻量创建本次请求的 agent
                            ▼
                          ERP OPENCLAW 主 Agent（编排）
                               ├─▶ procurement-analyst 子 Agent（查数据 / 抓报价 / 分析 / 出报告）
                               └─▶ procurement-order  子 Agent（校验 / 创建 / 更新订单）
                                     │  通过 MCP 工具
                                     ▼
                                     ERP MCP :8000/mcp
                                      ──▶ Java ERP :8080/api 
                                        ──▶ MySQL motorparts_db
```
1. 前端向 `/api/chat/stream` 发送用户消息。
2. FastAPI 为用户获取或创建独立沙箱，，并创建本次请求的 Agent graph。【多例】##===================================##===================================
3. 主Agent注入用户上下文----与记忆，按需同步skills，工具，，，【意图识别】并判断是直接回答还是委派子Agent。
4. `procurement-analyst` 查询业务数据、抓取供应商页面、执行分析并生成报告；`procurement-order` 校验订单字段并调用订单工具。
5. ERP MCP 将业务工具转换为 Java REST 请求。----【先】先补充数据----【后】创建或更新订单前，LangGraph 中断执行并等待前端提交审批决定。
6. 文本、工具状态、图片、中断和完成信号通过 SSE 持续返回前端；checkpoint 写入 MongoDB，便于恢复会话。



官网：https://docs.langchain.com/oss/python/deepagents/overview
官网马：https://www.mashibing.com/course/2959 ----
基础：：
沧海九粟【书】==白鲸datawhalechina::https://github.com/datawhalechina/deepagents-in-action
## ----参考url
liqiangZzz最早：：https://github.com/liqiangZzz/ERP_OPENCLAW --
todo
ooo1208[包含自进化]：：https://github.com/ooo1208/ERP_OPENCLAW --
liuchen6667：：https://github.com/liuchen6667/deepseek-auto-evolving-harness


## ---多模态
datawhalechina的start-mllm：：https://github.com/datawhalechina/start-mllm


