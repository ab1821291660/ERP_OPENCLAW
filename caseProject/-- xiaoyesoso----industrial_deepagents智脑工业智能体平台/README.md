# 智脑 · 工业智能体平台（Industrial DeepAgents Platform）
git：：https://github.com/xiaoyesoso/industrial_deepagents
基于 [LangChain deepagents](https://docs.langchain.com/oss/python/deepagents) 的多租户工业智能体平台，面向装备制造（电梯/升降装备）非标订单的技术方案设计场景：自然语言需求 → 参数识别 → 规范检索 → 选型计算 → 方案输出，全程可观测、可评估。

[English README](./README_EN.md)

## 核心功能

- **多租户与 RBAC**：JWT 认证，租户/项目/用户三级隔离，owner / admin / member 角色。
- **项目管理与对话**：项目隔离的对话历史，SSE 流式回复（思考链 / token / 工具调用事件实时展示）。
- **deepagents 智能体**：虚拟文件系统（读/写/编辑/glob/grep）、子 Agent 委派（`task`）、任务规划（TodoList）、可选本地沙箱执行（`execute`）。
- **平台技能库（Agent Skills）**：12 个独立 Skill，符合官方目录规范（`SKILL.md` + YAML frontmatter + 渐进披露）：
  - `knowledge-search` 知识库检索（真实种子数据）
  - `web-search` 联网搜索（DuckDuckGo 免费检索，无需 API Key）
  - `text-file-parser` / `pdf-parser` / `office-parser` / `spreadsheet-parser` / `image-drawing-parser` 五类文件解析
  - `erp-purchase` / `equipment-logs` / `finance-info` / `drawing-recognition` / `solution-review`（演示数据，正式接入需对接客户系统）
- **文件上传**：multipart 上传 → MinIO 对象存储（`tenant/project/file/文件名` 键），SQLite 仅存元数据；大小/MIME/类型校验；按扩展名映射到独立解析 Skill。
- **行业工具链**：设计规范检索、井道尺寸计算（确定性规则）、工艺路线、设备参数、售后规则、计算器、联网搜索。
- **
- **
- **评估**：LLM-as-judge 评分（逐条断言 + 模型评审），评估集与运行记录管理。
- **可观测性**：每次运行落 trace（工具调用、token、延迟、错误），可选接入 Langfuse。
- **前端**：React 18 单文件应用（无构建步骤），门户 + 后台双模式，Markdown 流式渲染（marked + DOMPurify 消毒）。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLite · pydantic-settings |
| 智能体 | deepagents · langchain-openai（OpenAI 兼容 API，默认智谱 GLM） |
| 对象存储 | MinIO（`minio` SDK） |
| 联网搜索 | DuckDuckGo（`ddgs`，免费无 Key） |
| 前端 | React 18 UMD · Babel standalone · marked + DOMPurify |
| 观测 | Langfuse（可选） |

## 快速开始

### 1. 环境要求

- Python 3.12+
- Docker（用于 MinIO）

### 2. 安装依赖

```bash
pip install fastapi "uvicorn[standard]" httpx "python-jose[cryptography]" \
  "passlib[bcrypt]" python-multipart pydantic pydantic-settings python-dotenv \
  pyyaml minio ddgs deepagents langchain-openai langfuse
```

### 3. 配置环境变量

在项目根目录创建 `.env`（**本文件不入库**）：

```ini
API_KEY=<你的 OpenAI 兼容模型 API Key>
BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=GLM-5.3-Flash
FLASH_LLM_MODEL=GLM-5.3-Flash
EMBEDDING_MODEL=embedding-3
RERANKER_MODEL=rerank

# MinIO（文件上传）
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=industrial-files

# 可选：Langfuse
# LANGFUSE_PUBLIC_KEY=...
# LANGFUSE_SECRET_KEY=...
# LANGFUSE_HOST=...
```

### 4. 启动 MinIO（可选，文件上传功能需要）

```bash
docker run -d --name minio-dev -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio server /data --console-address ':9001'
```




### 5. 启动服务
```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765 ##===================================
```
打开 http://localhost:8765 ，首次访问注册账号即可（演示账号：`demo@local` / `demo1234`）。 ##===================================
> 默认数据库与文件根目录位于 `backend/data/`（运行时生成，不入库）。未配置 MinIO 时上传接口返回 503，不影响其他功能。

## 目录结构
```
backend/
├── app/
│   ├── api/            # 路由：auth / tenants租户 / agents / tools / threads / evals / traces / industrial
│   ├── services/       # agent_factory / runtime_service / builtin_tools / industrial_tools / minio_service ...
│   ├── repositories/   # SQL 访问层
│   ├── config.py       # 环境配置
│   ├── db.py           # 建表 / 迁移 / 种子数据
│   └── main.py         # 应用入口（挂载前端）
├── skills/             # 平台技能库（deepagents Agent Skills）
├── tests/              # pytest（88 个用例）
└── data/               # 运行时数据（不入库）
frontend/
└── index.html          # 单文件 React 应用
```

## API 一览（前缀 `/api`）
| 模块 | 端点示例 | 说明 |
|---|---|---|
| 认证 | `POST /auth/signup` · `POST /auth/login` | 注册 / 登录，返回 JWT |
| 项目 | `GET /projects` | 租户内项目列表 |
| 对话 | `POST /threads` · `POST /threads/{id}/runs` | 创建对话；SSE 流式执行 |
| 文件 | `POST /industrial/files` · `POST /industrial/files/{id}/parse` | MinIO 上传；标记解析 Skill 队列 |
| 技能 | `GET /industrial/skills` | 技能目录（含接通状态） |
| 工具 | `GET /tools` | 平台 / 沙箱 / 能力开关目录 |
| 评估 | `POST /evals/runs` | 评估集执行（LLM 评审） |
| 观测 | `GET /traces` | 运行 trace 与事件 |

## 测试
```bash
cd backend && python -m pytest tests/ -q
```

## 边界说明（诚实声明）
- `web-search` 为 DuckDuckGo 免费检索，只返回摘要，不抓取网页正文； 偶发限流时自动降级为本地知识库回答。
- OCR、CAD 图纸真实解析、三维模型解析当前未接通，相关 Skill 明确标注为不可用/演示能力，不伪造解析结果。
- `erp-purchase` / `equipment-logs` / `finance-info` 等技能数据源为演示样例，正式使用需对接客户系统。



