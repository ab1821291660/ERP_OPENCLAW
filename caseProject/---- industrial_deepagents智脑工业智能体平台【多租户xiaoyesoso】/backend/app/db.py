"""SQLite connection management, schema bootstrap and seed data."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, slug)
);
CREATE TABLE IF NOT EXISTS memberships (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, user_id)
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    tools TEXT NOT NULL DEFAULT '[]',
    sandbox_enabled INTEGER NOT NULL DEFAULT 0,
    planning_enabled INTEGER NOT NULL DEFAULT 0,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,
    tokens TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_datasets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_cases (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES eval_datasets(id),
    input TEXT NOT NULL,
    expected TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    dataset_id TEXT NOT NULL REFERENCES eval_datasets(id),
    agent_id TEXT NOT NULL REFERENCES agents(id),
    judge TEXT NOT NULL CHECK(judge IN ('contains','exact','llm_judge')),
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
    total INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    mean_score REAL NOT NULL DEFAULT 0,
    pass_rate REAL NOT NULL DEFAULT 0,
    total_ms INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES eval_runs(id),
    case_id TEXT NOT NULL REFERENCES eval_cases(id),
    idx INTEGER NOT NULL,
    output TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    judge_reason TEXT NOT NULL DEFAULT '',
    judge_error TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens TEXT,
    trace_run_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    thread_id TEXT,
    agent_id TEXT NOT NULL,
    user_id TEXT,
    source TEXT NOT NULL CHECK(source IN ('chat','evaluation')),
    eval_run_id TEXT,
    eval_result_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
    input_preview TEXT NOT NULL DEFAULT '',
    output_preview TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    tokens TEXT,
    error TEXT NOT NULL DEFAULT '',
    langfuse_trace_id TEXT NOT NULL DEFAULT '',
    langfuse_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS industrial_knowledge (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    family TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS industrial_files (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), project_id TEXT NOT NULL REFERENCES projects(id),
    filename TEXT NOT NULL, object_name TEXT NOT NULL UNIQUE, content_type TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
    parser_skill TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'uploaded', created_at TEXT NOT NULL, uploaded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_industrial_files_scope ON industrial_files(tenant_id, project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_cat ON industrial_knowledge(category, family);
CREATE INDEX IF NOT EXISTS idx_results_run ON eval_results(run_id, idx);
CREATE INDEX IF NOT EXISTS idx_runs_tenant ON agent_runs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_threads_tenant ON threads(tenant_id, updated_at DESC);
"""

DEFAULT_AGENT_PROMPT = (
    "你是「日常办公助手」，一个基于 deepagents 框架的 AI 助理。"
    "你可以读写项目文件、把复杂任务委派给子 Agent；"
    "被启用的工具可以直接调用。回答请使用与用户相同的语言，简洁准确。"
)

_lock = threading.Lock()
_initialized: set[str] = set()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or get_settings()
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(settings: Settings | None = None, *, seed: bool = True) -> None:
    settings = settings or get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)##BACKEND_ROOT / "data"
    db_file = str(settings.db_path)##self.data_path / "platform.db"
    with _lock:
        if db_file in _initialized:
            return
        conn = connect(settings)##===================================
        try:
            _migrate_projects(conn)##===================================
            _migrate_files(conn)##===================================
            conn.executescript(_DDL)
            if seed:
                _seed(conn)##===================================
                _seed_industrial(conn)##===================================
            conn.commit()
        finally:
            conn.close()
        _initialized.add(db_file)

def ________(self):pass
def _migrate_files(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='industrial_files'"
    ).fetchone()
    if row:
        columns = {item[1] for item in conn.execute("PRAGMA table_info(industrial_files)")}
        if "uploaded_by" not in columns:
            conn.execute("ALTER TABLE industrial_files ADD COLUMN uploaded_by TEXT")


def _migrate_projects(conn: sqlite3.Connection) -> None:
    """Rename the legacy `workspaces` table/columns to `projects`.

    Runs BEFORE the DDL script so legacy databases do not end up with two
    parallel tables. SQLite >= 3.25 is required for RENAME COLUMN; its
    ALTER TABLE RENAME also updates REFERENCES clauses in child tables.
    """
    has_legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspaces'"
    ).fetchone()
    has_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'"
    ).fetchone()
    if not has_legacy or has_new:
        return
    if sqlite3.sqlite_version_info < (3, 25, 0):
        raise RuntimeError(
            "SQLite >= 3.25 is required to migrate workspaces -> projects; "
            "please upgrade Python or rebuild the database file."
        )
    conn.execute("ALTER TABLE workspaces RENAME TO projects")
    for table in ("threads", "agents"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "workspace_id" in cols:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN workspace_id TO project_id")


# ---------- industrial brain seed data ----------
# Demo-grade engineering rule set for elevator / lifting-equipment non-standard
# design. Values are teaching samples, always quote the clause and note that the
# customer's latest official design specification takes precedence.
_KNOWLEDGE_SEED: list[tuple[str, str, str, str, list[str]]] = [
    # --- 设计标准 / ESW ---
    ("设计标准", "ESW", "ESW 梯型井道尺寸余量规则",
     "ESW 客梯最小井道尺寸按轿厢净尺寸加余量确定：中分门井道宽度=轿厢宽+200mm（两侧立柱各100），"
     "旁开/单开门井道宽度=轿厢宽+开门侧预留450mm+对重侧预留（对重侧置250mm/后置0）+侧壁余量200mm；"
     "井道深度=轿厢深+门侧余量（中分150mm/旁分200mm）+后侧余量250mm。规则为示例经验值，"
     "实际以厂家最新设计规范为准。",
     ["井道", "轿厢", "中分门", "旁开门", "单开门", "对重", "余量"]),
    ("设计标准", "ESW", "ESW 载重与速度适用范围",
     "ESW 梯型载重适用 320/400/450/630/800/1000/1250/1600 kg，额定速度适用 1.0/1.5/1.75/2.0/2.5 m/s；"
     "非标订单超出该范围时不得直接选型，须转研发评审。",
     ["载重", "速度", "选型", "ESW"]),
    ("设计标准", "ESW", "ESW 开门型式与开门宽度",
     "中分门净开门宽度常用 700/800/900/1000/1100/1200mm；旁开（单开）门用于井道宽度受限场景，"
     "厅门侧需额外预留门机及门套空间（见井道余量规则）。对重侧置时开门侧不得与对重同侧冲突。",
     ["开门", "中分门", "旁开门", "门机", "门套"]),
    ("设计标准", "ESW", "ESW 顶层高度与底坑深度",
     "速度1.5m/s 时标准顶层高度≥4200mm、底坑深度≥1500mm；速度每提高0.5m/s，顶层高度建议增加300mm、"
     "底坑深度增加100mm。非标井道不满足时应选配矮顶/浅底坑方案并重新会签。",
     ["顶层高度", "底坑", "井道", "速度"]),
    # --- 设计标准 / ESW03 ---
    ("设计标准", "ESW03", "ESW03 梯型选型边界",
     "ESW03 为升级系列小机房/无机房客梯，载重 400–1250kg、速度 1.0–2.0m/s；"
     "载重450kg 速度1.5m/s 为标准档，可直接按规则出方案；载重≥1000kg 或速度≥2.0m/s 需研发复核曳引能力。",
     ["ESW03", "选型", "载重", "速度", "曳引"]),
    ("设计标准", "ESW03", "ESW03 无机房井道要求",
     "ESW03 无机房方案井道宽度在同等轿厢下较 ESW 有机房方案增加 100mm（控制柜侧嵌墙空间），"
     "井道深度余量不变；顶层高度需≥4350mm（1.5m/s）。",
     ["ESW03", "无机房", "井道", "顶层高度", "控制柜"]),
    # --- 设备参数 ---
    ("设备参数", "ESW", "ESW 主机与控制柜参数",
     "450kg/1.5m/s 档标配永磁同步曳引机（功率约4.0kW）、变频控制柜（VVVF）、220/380V 三相供电；"
     "1000kg/1.75m/s 档主机功率约6.7kW。具体以BOM选型单为准。",
     ["主机", "曳引机", "控制柜", "功率", "ESW"]),
    ("设备参数", "ESW03", "ESW03 门系统与轿厢参数",
     "ESW03 标配变频中分门机，开门时间≤2.5s（800mm开门）；轿厢净高标准2300mm，"
     "吊顶+风扇占位约200mm，轿厢外高按2500mm 预留。",
     ["ESW03", "门机", "轿厢", "开门时间", "净高"]),
    ("设备参数", "", "通用轿厢装潢与重量修正",
     "标准发纹不锈钢轿厢自重按载重的约 0.95 倍估算；加装玻璃轿壁/大理石地板时每台额外增加 80–200kg 自重，"
     "主机选型需同步复核。",
     ["轿厢", "装潢", "自重", "主机"]),
    # --- 工艺路线 ---
    ("工艺路线", "ESW", "ESW 非标订单工艺路线",
     "ESW 非标订单标准工艺路线：需求受理→技术参数确认（梯型/载重/速度/轿厢/开门/对重）→"
     "井道与土建校核→方案设计与报价→合同评审→钣金/轿厢加工→曳引与门系统装配→厂内联调→发货→现场安装→验收。"
     "其中井道校核不通过则退回方案设计。",
     ["工艺路线", "非标", "ESW", "流程", "会签"]),
    ("工艺路线", "ESW03", "ESW03 非标订单工艺路线",
     "ESW03 工艺路线与 ESW 一致，但在方案设计后增加无机房布置评审（控制柜/主机梁承载）节点；"
     "无机房方案必须在合同评审前完成顶层与控制柜侧墙确认。",
     ["工艺路线", "ESW03", "无机房", "评审"]),
    # --- 售后规则 ---
    ("售后规则", "", "质保与维保通用规则",
     "整梯自验收合格之日起免费质保 18 个月（或发货后 24 个月，以先到为准）；"
     "质保范围覆盖制造质量缺陷，不当使用、土建沉降、不可抗力除外。质保期内每 3 个月一次例行维保。",
     ["售后", "质保", "维保"]),
    ("售后规则", "", "售后维修响应规则",
     "故障响应：市区 2 小时到达、郊区 4 小时到达；困人故障按应急流程 30 分钟内远程响应、1 小时内到场。"
     "常见根因分类：门系统（约35%）、控制/变频（约25%）、曳引与悬挂（约20%）、其他（约20%）。",
     ["售后", "维修", "响应", "故障", "根因分析"]),
    ("售后规则", "ESW", "ESW 专项售后注意事项",
     "ESW 旁开门机型需在半年保时重点检查门机滑轨与重锤间隙；对重侧置井道需检查侧导轨压板力矩。",
     ["售后", "ESW", "旁开门", "对重", "维保"]),
]

INDUSTRIAL_AGENT_NAME = "智脑 · 非标方案专家"
INDUSTRIAL_AGENT_TOOLS = [
    "query_design_rules", "shaft_size_calculator", "process_route",
    "equipment_params", "after_sales_policy", "calculate", "web_search",
]
INDUSTRIAL_AGENT_PROMPT = (
    "你是「智脑 · 非标方案专家」，服务于装备制造（电梯/升降装备）非标订单的技术方案设计。"
    "工作要求：1) 收到客户自然语言需求后，先识别梯型/设备族、载重、速度、轿厢尺寸、开门型式、对重位置等关键参数，"
    "参数缺失或越界时先列出待确认项并追问，不要编造规范数值；"
    "2) 必须先调用 query_design_rules 检索适用设计条款，涉及尺寸/选型计算时调用 shaft_size_calculator 等工具，"
    "需要工序、设备参数、售后信息时分别调用 process_route / equipment_params / after_sales_policy；"
    "3) 回答固定结构：「配置参数」逐条回显 →「计算/选型结果」给出结论与数值并引用适用条款 →「待确认项」；"
    "4) 数值结论以工具返回为准，并提示以厂家最新设计规范为准；使用与客户相同的中文，简洁专业。"
)


def _seed_industrial(conn: sqlite3.Connection) -> None:
    """Seed the global industrial knowledge base and the per-tenant expert agent.

    Knowledge rows are seeded once (empty table guard). The expert agent is
    created for every tenant that does not yet own one, so existing demo
    databases receive it on next startup as well.
    """
    from .util import new_id

    now = utcnow()
    if conn.execute("SELECT COUNT(*) c FROM industrial_knowledge").fetchone()["c"] == 0:
        for category, family, title, content, tags in _KNOWLEDGE_SEED:
            conn.execute(
                "INSERT INTO industrial_knowledge(id,category,family,title,content,tags,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (new_id(), category, family, title, content, json.dumps(tags, ensure_ascii=False), now),
            )

    # One industrial expert per tenant (idempotent by tenant_id + name).
    tenants = conn.execute("SELECT id FROM tenants").fetchall()
    for t in tenants:
        exists = conn.execute(
            "SELECT id, tools FROM agents WHERE tenant_id=? AND name=?",
            (t["id"], INDUSTRIAL_AGENT_NAME),
        ).fetchone()
        if exists:
            # Migration: existing experts predate the web_search tool; append it once.
            try:
                tools = json.loads(exists["tools"] or "[]")
            except (TypeError, json.JSONDecodeError):
                tools = []
            if isinstance(tools, list) and "web_search" not in tools:
                tools.append("web_search")
                conn.execute(
                    "UPDATE agents SET tools=?, updated_at=? WHERE id=?",
                    (json.dumps(tools, ensure_ascii=False), utcnow(), exists["id"]),
                )
            continue
        project = conn.execute(
            "SELECT id FROM projects WHERE tenant_id=? ORDER BY created_at LIMIT 1", (t["id"],),
        ).fetchone()
        if not project:
            continue
        owner = conn.execute(
            "SELECT user_id FROM memberships WHERE tenant_id=? ORDER BY created_at LIMIT 1",
            (t["id"],),
        ).fetchone()
        conn.execute(
            """INSERT INTO agents(id,tenant_id,project_id,name,description,system_prompt,model,tools,
               sandbox_enabled,planning_enabled,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,0,1,?,?,?)""",
            (
                new_id(), t["id"], project["id"], INDUSTRIAL_AGENT_NAME,
                "装备制造非标订单方案专家：自动检索设计规范、井道尺寸计算、工艺路线与售后规则",
                INDUSTRIAL_AGENT_PROMPT, "", json.dumps(INDUSTRIAL_AGENT_TOOLS, ensure_ascii=False),
                owner["user_id"] if owner else None, now, now,
            ),
        )


def _seed(conn: sqlite3.Connection) -> None:
    """Create the demo account, its tenant/project and a default agent."""
    from .security import hash_password
    from .util import new_id, slugify

    row = conn.execute("SELECT 1 FROM users WHERE email = ?", ("demo@local",)).fetchone()
    if row:
        return
    now = utcnow()
    user_id, tenant_id, ws_id, agent_id = new_id(), new_id(), new_id(), new_id()
    conn.execute(
        "INSERT INTO users(id,email,password_hash,display_name,created_at) VALUES(?,?,?,?,?)",
        (user_id, "demo@local", hash_password("demo1234"), "Demo User", now),
    )
    conn.execute(
        "INSERT INTO tenants(id,name,slug,created_at) VALUES(?,?,?,?)",
        (tenant_id, "Demo 组织", "demo-org", now),
    )
    conn.execute(
        "INSERT INTO projects(id,tenant_id,name,slug,created_at) VALUES(?,?,?,?,?)",
        (ws_id, tenant_id, "默认项目", "default", now),
    )
    conn.execute(
        "INSERT INTO memberships(id,tenant_id,user_id,role,created_at) VALUES(?,?,?,?,?)",
        (new_id(), tenant_id, user_id, "owner", now),
    )
    conn.execute(
        """INSERT INTO agents(id,tenant_id,project_id,name,description,system_prompt,model,tools,
           sandbox_enabled,planning_enabled,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,0,0,?,?,?)""",
        (
            agent_id, tenant_id, ws_id, "日常办公助手",
            "deepagents 驱动的默认助理：文件处理、任务委派与常用工具",
            DEFAULT_AGENT_PROMPT, "", json.dumps(["calculate", "current_datetime", "word_count"]),
            user_id, now, now,
        ),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
