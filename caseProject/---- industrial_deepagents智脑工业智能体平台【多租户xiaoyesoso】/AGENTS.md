# AGENTS.md — AI 编码代理工作约定

本文件约束所有在本仓库工作的 AI 编码代理（Claude Code / TRAE 等）的研发行为。

## 1. 项目概述

「智脑」工业智能体平台：基于 [deepagents](https://docs.langchain.com/oss/python/deepagents) 的多租户智能体平台，服务装备制造（电梯/升降装备）非标订单的技术方案设计。技术栈：FastAPI + SQLite + MinIO + React 18（单文件）+ LangChain deepagents。

## 2. 架构分层（严格遵守）

```
backend/app/
├── api/            # 路由层：只做参数校验、权限、编排，不写业务逻辑
├── services/       # 服务层：业务编排（agent_factory、runtime_service、minio_service...）
├── repositories/   # 存储层：SQL 访问，一个领域一个模块
├── models.py       # Pydantic 模型
├── db.py           # SQLite 建表、迁移、种子数据
├── security.py    # JWT / RBAC
└── config.py      # pydantic-settings，读项目根 .env
```

- 路由 → 服务 → 仓库，禁止跨层直调。
- 数据库连接由 `api/deps.py` 的 `get_db` 依赖管理；LangChain 工具内自开短连接（见 `services/industrial_tools.py`）。

## 3. 常用命令

```bash
# 语法检查
cd backend && python -m py_compile app/*.py app/api/*.py app/services/*.py

# 测试（必须用 miniconda python，系统 python3 无 pytest）
cd backend && /Users/souljoy/miniconda3/bin/python -m pytest tests/ -q

# 启动开发服务（同源托管前端，默认 8765 端口）
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8765

# OpenSpec 变更校验
openspec validate <change-name> --json
```

- 改静态目录/路由后必须重启 uvicorn；请求 404 先排查旧进程残留（`lsof -ti:8765`）。

## 4. 前端约定

- 唯一入口 `frontend/index.html`：React 18 UMD + `@babel/standalone@7.x`（锁 7.x，Babel 8 不兼容）、`marked@12` + `dompurify@3`（Markdown 渲染，经 DOMPurify 消毒）。
- 无构建步骤、无 npm 依赖；后端 `StaticFiles(html=True)` 挂载 `/`，与 API 同源。
- 组件按能力域拆分；异步加载必须有 loading/错误态。
- 事件处理函数引用可变状态时用 ref 模式，避免闭包过期。
- 助手消息按 Markdown 渲染；用户消息保持纯文本（防注入）。

## 5. Skills 技能库约定（deepagents 官方规范）

- 位置：`backend/skills/<skill-name>/SKILL.md`，可带 `references/` 子目录。
- `SKILL.md` 必须有 YAML frontmatter，至少含 `name`（小写连字符，与目录名一致）与 `description`；`metadata.label/icon/category` 供前端目录展示。
- Agent 启动只加载摘要（渐进披露），命中后经 `read_file` 读取全文——禁止把长指令内联进 system prompt。
- 虚拟挂载路径 `/skills/`，只读共享库；目录 API（`/api/industrial/skills`）以 frontmatter 为唯一事实来源。
- 未真实接通的数据源（OCR、CAD、ERP、设备日志、财务系统）必须在 SKILL.md 中明确声明为演示数据，禁止伪造结果。

## 6. 安全红线

- 绝不提交 `.env`、`openspec/`、`extra_doc/`、`.trae/`、`backend/data/`、`*.profraw`（已入 .gitignore）。
- 绝不在日志、README、回复中打印 API_KEY 内容。
- 文件上传必须校验登录、项目归属、扩展名、MIME、大小；存储只进 MinIO（失败即报错，禁止回退本地文件系统）；SQLite 只存元数据与对象键。
- API 错误响应不得泄露堆栈（`main.py` 统一 500 处理，明细进 trace 表）。

## 7. 研发流程（SDD）

1. 新需求先建 OpenSpec 变更（proposal / specs / design / tasks 四件套，中文），`openspec validate` 通过后再写代码。
2. 按 `tasks.md` 顺序实现，完成一项勾一项；每个里程碑跑 pytest 全量回归。
3. 涉及 LLM 的改动必须用真实模型 API 实测（SSE 链路）；涉及前端必须在浏览器实操验证。
4. 修复 bug：先复现 → 读日志定位 → 最小改动修复 → 重跑用例 + 全量回归；禁止用跳过/注释测试的方式"通过"。

## 8. 语言与文风

- 用户可见产物（spec、README、汇报）：中文。
- 代码与注释：英文。
- 提交信息：`feat:/fix:/docs:` + 英文摘要。

## 9. 禁用词

- 全项目禁止出现特定的历史旧品牌词（两字词，以「工」开头、「控」结尾），用户明确要求移除；规则与文档中亦不得原样写出。提交前扫描确认。

## 10. 交付基线

- pytest 全部通过；新增功能必须补测试。
- 每个提供 HTTP API 的能力，前端必须有可见的操作入口。
- git 提交需用户明确要求后进行。
