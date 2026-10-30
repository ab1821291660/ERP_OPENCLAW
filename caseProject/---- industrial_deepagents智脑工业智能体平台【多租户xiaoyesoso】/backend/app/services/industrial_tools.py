"""Industrial-domain agent tools: knowledge search + deterministic calculators.

Tools here open their own short-lived SQLite connection because LangChain tools
run outside the request's DB dependency. The knowledge base is a global
(tenant-independent) industry rule library.
"""
from __future__ import annotations

from langchain_core.tools import tool

from ..db import connect
from ..repositories import knowledge as knowledge_repo
from ..util import truncate

# ---------- deterministic shaft sizing rules (mirrors seeded knowledge) ----------
_ALLOWED_LOADS = (320, 400, 450, 630, 800, 1000, 1250, 1600)
_ALLOWED_SPEEDS = (1.0, 1.5, 1.75, 2.0, 2.5)
_DOOR_TYPES = {
    "中分": ("中分门", "center"),
    "中分门": ("中分门", "center"),
    "center": ("中分门", "center"),
    "旁分": ("旁开门", "side"),
    "旁开": ("旁开门", "side"),
    "旁开门": ("旁开门", "side"),
    "单开": ("单开门", "side"),
    "单开门": ("单开门", "side"),
    "side": ("旁开门", "side"),
}
_COUNTERWEIGHT = {
    "后置": "rear", "后对重": "rear", "rear": "rear",
    "侧置": "side", "侧对重": "side", "side": "side",
    "左置": "side_left", "左侧": "side_left", "left": "side_left",
    "右置": "side_right", "右侧": "side_right", "right": "side_right",
}
_SIDE_WALL_MARGIN_MM = 200          # both side walls combined
_DOOR_OPENING_MARGIN_MM = 450        # side-opening door machine allowance
_COUNTERWEIGHT_SIDE_MARGIN_MM = 250  # side-mounted counterweight rail space
_DOOR_DEPTH = {"center": 150, "side": 200}
_REAR_DEPTH_MARGIN_MM = 250


def compute_shaft_size(*, family: str, load_kg: float, speed_ms: float,
                       car_width_mm: float, car_depth_mm: float,
                       door_type: str, counterweight: str) -> dict:
    """Pure deterministic rule evaluation. Raises ValueError on bad input."""
    fam = (family or "").strip().upper()
    if fam not in ("ESW", "ESW03"):
        raise ValueError(f"不支持的梯型/设备族：{family!r}，当前规则支持 ESW / ESW03")
    if load_kg not in _ALLOWED_LOADS:
        raise ValueError(f"不支持的载重 {load_kg}kg，允许档位：{', '.join(map(str, _ALLOWED_LOADS))} kg")
    if speed_ms not in _ALLOWED_SPEEDS:
        raise ValueError(f"不支持的速度 {speed_ms}m/s，允许档位：{', '.join(map(str, _ALLOWED_SPEEDS))} m/s")
    if car_width_mm <= 0 or car_depth_mm <= 0:
        raise ValueError("轿厢宽/深必须为正数（单位 mm）")

    door = _DOOR_TYPES.get((door_type or "").strip())
    if not door:
        raise ValueError(f"不支持的开门型式：{door_type!r}，允许：中分门 / 旁开门(单开门)")
    door_label, door_mode = door

    cw = _COUNTERWEIGHT.get((counterweight or "").strip())
    if not cw:
        raise ValueError(f"不支持的对重位置：{counterweight!r}，允许：后置 / 侧置(左置/右置)")

    # Width
    if door_mode == "center":
        shaft_width = car_width_mm + _SIDE_WALL_MARGIN_MM
    else:
        cw_margin = _COUNTERWEIGHT_SIDE_MARGIN_MM if cw in ("side", "side_left", "side_right") else 0
        shaft_width = car_width_mm + _DOOR_OPENING_MARGIN_MM + cw_margin + _SIDE_WALL_MARGIN_MM

    # Depth (counterweight position does not change depth; door type does)
    shaft_depth = car_depth_mm + _DOOR_DEPTH[door_mode] + _REAR_DEPTH_MARGIN_MM

    # ESW03 machine-room-less needs extra width on the controller side
    if fam == "ESW03":
        shaft_width += 100

    return {
        "family": fam,
        "load_kg": int(load_kg),
        "speed_ms": speed_ms,
        "car_width_mm": int(car_width_mm),
        "car_depth_mm": int(car_depth_mm),
        "door_type": door_label,
        "counterweight": {"rear": "后置", "side": "侧置",
                         "side_left": "侧置(左置)", "side_right": "侧置(右置)"}[cw],
        "shaft_width_mm": int(shaft_width),
        "shaft_depth_mm": int(shaft_depth),
        "rule": "ESW/ESW03 井道尺寸余量规则（示例经验值，以厂家最新设计规范为准）",
    }


def ____():pass
# ---------- knowledge search helpers ----------
def _search_knowledge(*, q: str, family: str = "", category: str = "",
                     limit: int = 5) -> list[dict]:
    conn = connect()
    try:
        return knowledge_repo.list_knowledge(
            conn, q=q, family=family.strip().upper(), category=category, limit=limit,
        )
    finally:
        conn.close()


def _format_clauses(rows: list[dict], empty_hint: str) -> str:
    if not rows:
        return f"未检索到适用条款。{empty_hint}"
    parts = []
    for i, r in enumerate(rows, 1):
        head = f"[{i}] 《{r['title']}》"
        if r.get("family"):
            head += f"（{r['family']}，{r['category']}）"
        else:
            head += f"（{r['category']}）"
        parts.append(f"{head}\n{r['content']}")
    return "\n\n".join(parts)


@tool
def query_design_rules(query: str, family: str = "") -> str:
    """检索工业大脑中的电梯/升降装备设计规范条款。

    Args:
        query: 检索关键词，如 "井道 中分门 对重"、"载重 速度 选型"。
        family: 可选设备族（梯型），如 ESW / ESW03；留空检索全部族系。
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: query 不能为空，请提供需要检索的设计规范关键词。"
    rows = _search_knowledge(q=query, family=family, category="设计标准")
    return truncate(_format_clauses(rows, "请补充梯型或关键参数后重试，或转技术部门会签。"), 4000)


@tool
def shaft_size_calculator(family: str, load_kg: float, speed_ms: float,
                          car_width_mm: float, car_depth_mm: float,
                          door_type: str, counterweight: str) -> str:
    """依据设计规范余量规则计算电梯最小井道宽度与深度。

    Args:
        family: 梯型/设备族，ESW 或 ESW03。
        load_kg: 额定载重 kg，允许 320/400/450/630/800/1000/1250/1600。
        speed_ms: 额定速度 m/s，允许 1.0/1.5/1.75/2.0/2.5。
        car_width_mm: 轿厢净宽 mm。
        car_depth_mm: 轿厢净深 mm。
        door_type: 开门型式：中分门 / 旁开门(单开门)。
        counterweight: 对重位置：后置 / 侧置(左置/右置)。
    """
    try:
        r = compute_shaft_size(
            family=family, load_kg=float(load_kg), speed_ms=float(speed_ms),
            car_width_mm=float(car_width_mm), car_depth_mm=float(car_depth_mm),
            door_type=door_type, counterweight=counterweight,
        )
    except (ValueError, TypeError) as exc:
        return f"ERROR: {exc}"
    return (
        "井道尺寸计算结果（依据：{rule}）：\n"
        "- 梯型：{family}\n- 载重：{load_kg}kg\n- 速度：{speed_ms}m/s\n"
        "- 轿厢尺寸：{car_width_mm}×{car_depth_mm}mm\n"
        "- 开门型式：{door_type}\n- 对重位置：{counterweight}\n"
        "最小井道尺寸：\n"
        "- 井道宽度：{shaft_width_mm}mm\n- 井道深度：{shaft_depth_mm}mm"
    ).format(**r)


@tool
def process_route(family: str, product: str = "") -> str:
    """查询非标订单的标准工艺路线（工序与会签节点）。

    Args:
        family: 设备族（梯型），如 ESW / ESW03。
        product: 可选具体产品/定制项描述，用于补充检索关键词。
    """
    q = f"{family} {product}".strip()
    rows = _search_knowledge(q=q, family=family, category="工艺路线")
    if not rows and product:
        rows = _search_knowledge(q=family, family=family, category="工艺路线")
    return truncate(_format_clauses(rows, "请确认设备族后重试，或联系工艺部门获取路线模板。"), 4000)


@tool
def equipment_params(family: str, part: str = "") -> str:
    """查询设备/部件参数（主机、控制柜、门系统、轿厢等）。

    Args:
        family: 设备族（梯型），如 ESW / ESW03；留空返回通用参数条款。
        part: 要查询的部件或参数名，如 "主机 功率"、"门机"。
    """
    rows = _search_knowledge(q=part or family, family=family, category="设备参数")
    return truncate(_format_clauses(rows, "请提供具体部件名称，或查阅最新 BOM 选型单。"), 4000)


@tool
def after_sales_policy(topic: str, family: str = "") -> str:
    """查询售后规则（质保期限、维保周期、维修响应、故障根因）。

    Args:
        topic: 主题，如 "质保"、"维保"、"维修 响应"、"根因分析"。
        family: 可选设备族，用于查询专项售后注意事项。
    """
    q = (topic or "").strip()
    if not q:
        return "ERROR: topic 不能为空，例如 质保 / 维保 / 维修响应。"
    rows = _search_knowledge(q=q, family=family, category="售后规则")
    if family and not rows:
        rows = _search_knowledge(q=q, category="售后规则")
    return truncate(_format_clauses(rows, "请联系售后管理部门确认最新政策。"), 4000)


def ________(self):pass
INDUSTRIAL_TOOLS = [
    query_design_rules,
    shaft_size_calculator,
    process_route,
    equipment_params,
    after_sales_policy,
]

