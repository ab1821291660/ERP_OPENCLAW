"""Industrial brain: deterministic calculator, knowledge/skills APIs, seed, SSE chain."""
import json

import pytest

from conftest import FakeChatModel, auth_headers, parse_sse, signup
from langchain_core.messages import AIMessage


# ---------------------------------------------------------------- deterministic core

def test_shaft_size_standard_sample():
    from app.services.industrial_tools import compute_shaft_size
    r = compute_shaft_size(
        family="ESW", load_kg=450, speed_ms=1.5,
        car_width_mm=1200, car_depth_mm=1200,
        door_type="中分门", counterweight="后置",
    )
    assert r["shaft_width_mm"] == 1400
    assert r["shaft_depth_mm"] == 1600
    assert r["door_type"] == "中分门"
    assert r["counterweight"] == "后置"


@pytest.mark.parametrize("door,cw,expected_w", [
    ("旁开门", "后置", 1850),   # 1200 + 450 + 0 + 200
    ("旁开门", "侧置", 2100),  # +250 counterweight side
    ("单开门", "左置", 2100),
])
def test_shaft_size_side_door_variants(door, cw, expected_w):
    from app.services.industrial_tools import compute_shaft_size
    r = compute_shaft_size(
        family="ESW", load_kg=450, speed_ms=1.5,
        car_width_mm=1200, car_depth_mm=1200,
        door_type=door, counterweight=cw,
    )
    assert r["shaft_width_mm"] == expected_w
    assert r["shaft_depth_mm"] == 1650  # side door depth: 1200+200+250


def test_shaft_size_esw03_extra_width():
    from app.services.industrial_tools import compute_shaft_size
    r = compute_shaft_size(
        family="esw03", load_kg=450, speed_ms=1.5,
        car_width_mm=1200, car_depth_mm=1200,
        door_type="中分门", counterweight="后置",
    )
    assert r["family"] == "ESW03"
    assert r["shaft_width_mm"] == 1500
    assert r["shaft_depth_mm"] == 1600


def test_shaft_size_deterministic():
    from app.services.industrial_tools import compute_shaft_size
    kwargs = dict(family="ESW", load_kg=630, speed_ms=1.75,
                  car_width_mm=1400, car_depth_mm=1300,
                  door_type="中分门", counterweight="后置")
    assert compute_shaft_size(**kwargs) == compute_shaft_size(**kwargs)


@pytest.mark.parametrize("bad", [
    dict(family="XXX"),
    dict(load_kg=500),
    dict(speed_ms=3.0),
    dict(car_width_mm=0),
    dict(car_depth_mm=-1),
    dict(door_type="卷闸门"),
    dict(counterweight="顶置"),
])
def test_shaft_size_rejects_bad_input(bad):
    from app.services.industrial_tools import compute_shaft_size
    kwargs = dict(family="ESW", load_kg=450, speed_ms=1.5,
                  car_width_mm=1200, car_depth_mm=1200,
                  door_type="中分门", counterweight="后置")
    kwargs.update(bad)
    with pytest.raises(ValueError):
        compute_shaft_size(**kwargs)


def test_calculator_tool_returns_error_text():
    from app.services.industrial_tools import shaft_size_calculator
    out = shaft_size_calculator.invoke({
        "family": "ESW", "load_kg": 999, "speed_ms": 1.5,
        "car_width_mm": 1200, "car_depth_mm": 1200,
        "door_type": "中分门", "counterweight": "后置",
    })
    assert out.startswith("ERROR:")
    out_ok = shaft_size_calculator.invoke({
        "family": "ESW", "load_kg": 450, "speed_ms": 1.5,
        "car_width_mm": 1200, "car_depth_mm": 1200,
        "door_type": "中分门", "counterweight": "后置",
    })
    assert "井道宽度：1400mm" in out_ok
    assert "井道深度：1600mm" in out_ok


# ------------------------------------------------------------------- HTTP APIs

def test_knowledge_and_skills_require_auth(client):
    assert client.get("/api/industrial/knowledge").status_code == 401
    assert client.get("/api/industrial/skills").status_code == 401


class FakeMinio:
    objects = {}
    put_error = None

    def __init__(self, settings=None, client=None):
        self.settings = settings

    def put(self, object_name, data, content_type):
        if self.put_error:
            raise self.put_error
        self.objects[object_name] = (bytes(data), content_type)


def _default_project(client, token):
    return client.get("/api/projects", headers=auth_headers(token)).json()[0]


def _upload(client, token, project_id, filename="note.txt", data=b"hello",
            content_type="text/plain"):
    return client.post(
        f"/api/industrial/files?project_id={project_id}",
        headers=auth_headers(token),
        files={"file": (filename, data, content_type)},
    )


def test_file_upload_requires_auth(client):
    resp = client.post(
        "/api/industrial/files?project_id=missing",
        files={"file": ("a.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 401


def test_file_upload_stores_object_in_minio_and_metadata_in_sqlite(client, monkeypatch):
    from app.api import industrial
    from app.db import connect

    FakeMinio.objects.clear()
    FakeMinio.put_error = None
    monkeypatch.setattr(industrial, "MinioService", FakeMinio)

    token, body = signup(client)
    project = _default_project(client, token)
    resp = _upload(client, token, project["id"], filename="采购说明.txt", data=b"hello minio")

    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["project_id"] == project["id"]
    assert saved["filename"] == "采购说明.txt"
    assert saved["size"] == 11
    assert saved["parser_skill"] == "text-file-parser"
    assert saved["status"] == "uploaded"

    object_name = next(iter(FakeMinio.objects))
    assert object_name.startswith(f"{body['user']['tenant_id']}/{project['id']}/")
    assert object_name.endswith("/采购说明.txt")
    assert FakeMinio.objects[object_name] == (b"hello minio", "text/plain")

    row = connect().execute(
        "SELECT * FROM industrial_files WHERE id=?", (saved["id"],)
    ).fetchone()
    assert row["object_name"] == object_name
    assert row["uploaded_by"] == body["user"]["id"]
    assert row["size"] == 11


@pytest.mark.parametrize(("filename", "content_type", "skill"), [
    ("a.txt", "text/plain", "text-file-parser"),
    ("a.md", "text/markdown", "text-file-parser"),
    ("a.pdf", "application/pdf", "pdf-parser"),
    ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "office-parser"),
    ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "spreadsheet-parser"),
    ("a.csv", "text/csv", "spreadsheet-parser"),
    ("a.png", "image/png", "image-drawing-parser"),
    ("a.dwg", "application/octet-stream", "image-drawing-parser"),
])
def test_file_upload_maps_type_to_parser_skill(client, monkeypatch, filename, content_type, skill):
    from app.api import industrial

    FakeMinio.objects.clear()
    FakeMinio.put_error = None
    monkeypatch.setattr(industrial, "MinioService", FakeMinio)
    token, _ = signup(client, email=f"user-{filename.replace('.', '-')}@example.com")
    project = _default_project(client, token)

    resp = _upload(client, token, project["id"], filename=filename,
                   data=b"payload", content_type=content_type)

    assert resp.status_code == 200, resp.text
    assert resp.json()["parser_skill"] == skill


def test_file_upload_rejects_unsupported_type_oversize_and_mime_mismatch(client, monkeypatch):
    from app.api import industrial

    FakeMinio.objects.clear()
    FakeMinio.put_error = None
    monkeypatch.setattr(industrial, "MinioService", FakeMinio)
    token, _ = signup(client)
    project = _default_project(client, token)

    bad_type = _upload(client, token, project["id"], filename="evil.exe",
                       data=b"x", content_type="application/octet-stream")
    assert bad_type.status_code == 415

    mismatch = _upload(client, token, project["id"], filename="note.txt",
                       data=b"x", content_type="application/pdf")
    assert mismatch.status_code == 415

    class SmallSettings:
        max_upload_size = 3

    monkeypatch.setattr(industrial, "get_settings", lambda: SmallSettings())
    oversize = _upload(client, token, project["id"], filename="big.txt",
                       data=b"abcd", content_type="text/plain")
    assert oversize.status_code == 413
    assert FakeMinio.objects == {}


def test_file_upload_translates_minio_errors(client, monkeypatch):
    from app.api import industrial
    from app.db import connect

    token, _ = signup(client)
    project = _default_project(client, token)
    monkeypatch.setattr(industrial, "MinioService", FakeMinio)

    FakeMinio.objects.clear()
    FakeMinio.put_error = RuntimeError("sdk missing")
    unavailable = _upload(client, token, project["id"])
    assert unavailable.status_code == 503

    FakeMinio.put_error = ValueError("boom")
    failed = _upload(client, token, project["id"])
    assert failed.status_code == 502
    assert connect().execute("SELECT COUNT(*) c FROM industrial_files").fetchone()["c"] == 0


def test_file_apis_are_scoped_by_tenant_and_parse_persists_status(client, monkeypatch):
    from app.api import industrial

    FakeMinio.objects.clear()
    FakeMinio.put_error = None
    monkeypatch.setattr(industrial, "MinioService", FakeMinio)

    alice, _ = signup(client, email="alice-files@example.com")
    alice_project = _default_project(client, alice)
    saved = _upload(client, alice, alice_project["id"]).json()

    bob, _ = signup(client, email="bob-files@example.com", org="BobOrg")
    bob_project = _default_project(client, bob)

    assert client.get(
        f"/api/industrial/files?project_id={alice_project['id']}",
        headers=auth_headers(bob),
    ).status_code == 404
    assert client.get(
        f"/api/industrial/files/{saved['id']}?project_id={alice_project['id']}",
        headers=auth_headers(bob),
    ).status_code == 404
    assert client.post(
        f"/api/industrial/files/{saved['id']}/parse?project_id={alice_project['id']}",
        headers=auth_headers(bob),
    ).status_code == 404

    listed = client.get(
        f"/api/industrial/files?project_id={alice_project['id']}",
        headers=auth_headers(alice),
    ).json()["items"]
    assert [item["id"] for item in listed] == [saved["id"]]

    detail = client.get(
        f"/api/industrial/files/{saved['id']}?project_id={alice_project['id']}",
        headers=auth_headers(alice),
    )
    assert detail.status_code == 200
    assert detail.json()["project_id"] == alice_project["id"]

    parse = client.post(
        f"/api/industrial/files/{saved['id']}/parse?project_id={alice_project['id']}",
        headers=auth_headers(alice),
    )
    assert parse.status_code == 200
    assert parse.json()["status"] == "queued"
    assert parse.json()["parser_skill"] == "text-file-parser"

    from app.db import connect
    row = connect().execute("SELECT status FROM industrial_files WHERE id=?", (saved["id"],)).fetchone()
    assert row["status"] == "queued"
    assert bob_project["id"] != alice_project["id"]


def test_safe_filename_removes_path_and_unsafe_characters():
    from app.api.industrial import _safe_filename

    assert _safe_filename("../../采购 清单(v1).txt") == "采购 清单(v1).txt"
    assert _safe_filename("a/b?.txt") == "b_.txt"


def test_knowledge_search_and_filters(client):
    token, _ = signup(client)
    h = auth_headers(token)

    resp = client.get("/api/industrial/knowledge", headers=h)
    assert resp.status_code == 200
    all_items = resp.json()["items"]
    assert len(all_items) >= 10
    assert all({"id", "category", "family", "title", "content", "tags"} <= set(i) for i in all_items)
    cats = {i["category"] for i in all_items}
    assert {"设计标准", "设备参数", "工艺路线", "售后规则"} <= cats

    # family exact filter
    esw = client.get("/api/industrial/knowledge?family=ESW", headers=h).json()["items"]
    assert esw and all(i["family"] == "ESW" for i in esw)

    # category exact filter
    routes = client.get("/api/industrial/knowledge?category=工艺路线", headers=h).json()["items"]
    assert len(routes) == 2 and all(i["category"] == "工艺路线" for i in routes)

    # AND keyword search
    hits = client.get("/api/industrial/knowledge?q=井道 对重", headers=h).json()["items"]
    assert hits and all("井道" in (i["title"] + i["content"] + "".join(i["tags"])) for i in hits)

    # combined
    one = client.get("/api/industrial/knowledge?family=ESW03&category=设计标准", headers=h).json()["items"]
    assert len(one) == 2 and all(i["family"] == "ESW03" for i in one)


def test_skills_catalog_dynamic_and_flags(client):
    token, _ = signup(client)
    resp = client.get("/api/industrial/skills", headers=auth_headers(token))
    assert resp.status_code == 200
    skills = resp.json()["items"]
    assert len(skills) >= 7
    by_name = {s["name"]: s for s in skills}
    # all packaged skills are callable deepagents skills now
    assert all(s["connected"] is True for s in skills)
    # data source wiring: knowledge base and DuckDuckGo web search are live
    assert by_name["knowledge-search"]["data_live"] is True
    assert by_name["web-search"]["data_live"] is True
    for name in ("erp-purchase", "equipment-logs", "finance-info"):
        assert by_name[name]["data_live"] is False
    # frontmatter metadata surfaced (label/icon/category)
    assert by_name["erp-purchase"]["label"] == "ERP采购查询"
    assert by_name["erp-purchase"]["icon"] == "cart"
    assert by_name["knowledge-search"]["description"]


def test_skills_library_frontmatter_valid():
    """Every packaged skill follows the Agent Skills conventions."""
    from app.api.industrial import SKILLS_DIR

    assert SKILLS_DIR.is_dir()
    dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir())
    assert len(dirs) >= 7
    for d in dirs:
        skill_md = d / "SKILL.md"
        assert skill_md.is_file(), f"missing SKILL.md in {d.name}"
        content = skill_md.read_text(encoding="utf-8")
        from app.api.industrial import _parse_frontmatter
        meta = _parse_frontmatter(content)
        name = str(meta.get("name", "")).strip()
        assert name == d.name, f"frontmatter name {name!r} != directory {d.name!r}"
        assert name and name == name.lower() and " " not in name
        assert meta.get("description"), f"empty description in {d.name}"
        extra = meta.get("metadata") or {}
        assert extra.get("label") and extra.get("icon"), f"missing metadata in {d.name}"


def test_skills_data_references_exist():
    """Demo-data skills ship references that the SKILL.md points to."""
    from app.api.industrial import SKILLS_DIR

    expected_refs = {
        "erp-purchase": "materials.json",
        "equipment-logs": "door-noise-log.txt",
        "finance-info": "cost-basis.md",
    }
    for skill, ref in expected_refs.items():
        skill_md = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        assert ref in skill_md, f"{skill}/SKILL.md does not reference {ref}"
        assert (SKILLS_DIR / skill / "references" / ref).is_file(), f"missing {skill}/references/{ref}"


def test_skills_middleware_loads_library(tmp_path):
    """deepagents SkillsMiddleware discovers all packaged skills via the /skills/ route."""
    from deepagents.backends import CompositeBackend, FilesystemBackend
    from deepagents.middleware.skills import _list_skills

    from app.api.industrial import SKILLS_DIR

    backend = CompositeBackend(
        default=FilesystemBackend(root_dir=str(tmp_path)),
        routes={"/skills/": FilesystemBackend(root_dir=str(SKILLS_DIR))},
    )
    skills = _list_skills(backend, "/skills/")
    names = {s["name"] for s in skills}
    assert {"knowledge-search", "web-search", "erp-purchase", "equipment-logs",
            "finance-info", "drawing-recognition", "solution-review",
            "text-file-parser", "pdf-parser", "office-parser",
            "spreadsheet-parser", "image-drawing-parser"} <= names
    for s in skills:
        assert s["description"]
        assert s["path"].startswith("/skills/") and s["path"].endswith("/SKILL.md")


def test_build_agent_mounts_skills(tmp_path, monkeypatch):
    """Non-sandbox agent compiles with the platform skills library mounted."""
    from app.services.agent_factory import SKILLS_DIR, build_agent, clear_cache

    clear_cache()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("API_KEY", "test-api-key-0000")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from app.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()

    agent = {
        "id": "ag-skills-01", "tenant_id": "t1", "name": "skill-tester",
        "system_prompt": "You are a tester.", "tools": [], "model": "",
        "sandbox_enabled": False, "planning_enabled": False,
        "updated_at": "2026-09-12T00:00:00Z",
    }
    compiled = build_agent(agent, "proj1", model=FakeChatModel(), settings=settings)
    assert compiled is not None
    assert SKILLS_DIR.is_dir()


def test_tools_registered_in_platform_catalog():
    from app.services.builtin_tools import PLATFORM_TOOLS, platform_tool_meta
    names = {t.name for t in PLATFORM_TOOLS}
    assert {"query_design_rules", "shaft_size_calculator", "process_route",
            "equipment_params", "after_sales_policy"} <= names
    assert "web_search" in names
    meta = platform_tool_meta()
    labels = {m["name"]: m["label"] for m in meta}
    assert labels["shaft_size_calculator"]
    assert labels["shaft_size_calculator"] != "shaft_size_calculator"
    assert labels["web_search"] == "联网搜索"
    assert any("DuckDuckGo" in m["description"] for m in meta if m["name"] == "web_search")


# ------------------------------------------------------------------ web search

def _patch_ddgs(monkeypatch, rows=None, error=None):
    from app.services import builtin_tools

    def fake_search(query, max_results):
        assert isinstance(query, str)
        assert 1 <= max_results <= 8
        if error is not None:
            raise error
        return rows or []

    monkeypatch.setattr(builtin_tools, "_duckduckgo_search", fake_search)


def test_web_search_tool_formats_results(monkeypatch):
    from app.services.builtin_tools import web_search
    _patch_ddgs(monkeypatch, rows=[
        {"title": "电梯制造与安装安全规范", "href": "https://example.com/gb7588", "body": "GB/T 7588.1-2020 摘要。"},
        {"title": "厂家公告", "href": "https://example.com/news", "body": "公告内容"},
    ])
    out = web_search.invoke({"query": "GB/T 7588.1-2020 乘客电梯"})
    assert "[1] 电梯制造与安装安全规范" in out
    assert "https://example.com/gb7588" in out
    assert "[2] 厂家公告" in out


def test_web_search_tool_degrades_on_backend_error(monkeypatch):
    from app.services.builtin_tools import web_search
    _patch_ddgs(monkeypatch, error=RuntimeError("rate limited"))
    out = web_search.invoke({"query": "电梯标准"})
    assert out.startswith("ERROR:")
    assert "联网检索暂不可用" in out


def test_web_search_tool_empty_query_and_results(monkeypatch):
    from app.services.builtin_tools import web_search
    out = web_search.invoke({"query": "   "})
    assert out.startswith("ERROR:")
    _patch_ddgs(monkeypatch, rows=[])
    out = web_search.invoke({"query": "量子电梯"})
    assert out == "未检索到相关公开资料。"


def test_web_search_tool_clamps_max_results(monkeypatch):
    from app.services.builtin_tools import web_search
    seen = {}
    from app.services import builtin_tools

    def fake_search(query, max_results):
        seen["n"] = max_results
        return [{"title": "t", "href": "https://e.com", "body": "b"}]

    monkeypatch.setattr(builtin_tools, "_duckduckgo_search", fake_search)
    web_search.invoke({"query": "电梯", "max_results": 50})
    assert seen["n"] == 8


def test_web_search_skill_declares_duckduckgo():
    from app.api.industrial import SKILLS_DIR

    content = (SKILLS_DIR / "web-search" / "SKILL.md").read_text(encoding="utf-8")
    assert "DuckDuckGo" in content
    assert "web_search" in content
    assert "降级" in content


def test_seed_migration_appends_web_search_to_existing_expert(client):
    """Legacy expert agents (created before web_search) get the tool on startup."""
    from app.db import INDUSTRIAL_AGENT_NAME, _seed_industrial, connect

    token, _ = signup(client, email="migrate@example.com")
    db = connect()
    try:
        row = db.execute(
            "SELECT id, tools FROM agents WHERE name=?", (INDUSTRIAL_AGENT_NAME,),
        ).fetchone()
        legacy_tools = ["query_design_rules", "shaft_size_calculator"]
        db.execute(
            "UPDATE agents SET tools=? WHERE id=?",
            (json.dumps(legacy_tools), row["id"]),
        )
        db.commit()
        _seed_industrial(db)
        db.commit()
        tools = json.loads(
            db.execute("SELECT tools FROM agents WHERE id=?", (row["id"],)).fetchone()["tools"]
        )
        assert "web_search" in tools
        # idempotent: re-running must not duplicate the entry
        _seed_industrial(db)
        db.commit()
        tools = json.loads(
            db.execute("SELECT tools FROM agents WHERE id=?", (row["id"],)).fetchone()["tools"]
        )
        assert tools.count("web_search") == 1
    finally:
        db.close()


# --------------------------------------------------------------------- seeding

def test_seed_idempotent(client):
    from app.db import _KNOWLEDGE_SEED, connect, init_db
    db = connect()
    from app.repositories.knowledge import get_knowledge_count
    first = get_knowledge_count(db)
    db.close()
    init_db()  # re-run seeding
    db = connect()
    second = get_knowledge_count(db)
    db.close()
    assert first == len(_KNOWLEDGE_SEED) == second


def test_default_industrial_agent_seeded_for_new_tenant(client):
    from app.db import INDUSTRIAL_AGENT_NAME, INDUSTRIAL_AGENT_TOOLS
    token, body = signup(client, email="bob@example.com", name="Bob")
    agents = client.get("/api/agents", headers=auth_headers(token)).json()
    experts = [a for a in agents if a["name"] == INDUSTRIAL_AGENT_NAME]
    assert len(experts) == 1
    expert = experts[0]
    assert expert["planning_enabled"] is True
    assert expert["sandbox_enabled"] is False
    for t in INDUSTRIAL_AGENT_TOOLS:
        assert t in expert["tools"]


# ------------------------------------------------------- SSE end-to-end chain

class _IndustrialFake(FakeChatModel):
    """Scripted model that drives the shaft calculator once, then finalizes."""

    def _pick_response(self, messages):
        from langchain_core.messages import HumanMessage, ToolMessage
        last_user = ""
        tool_text = ""
        saw_result = False
        for m in messages:
            if isinstance(m, HumanMessage):
                last_user = m.content if isinstance(m.content, str) else str(m.content)
            elif isinstance(m, ToolMessage):
                saw_result = True
                tool_text = m.content if isinstance(m.content, str) else str(m.content)
        if saw_result:
            return AIMessage(content=f"FINAL 井道结论：{tool_text}")
        if "井道" in last_user and "shaft_size_calculator" in self.tool_names:
            return AIMessage(content="", tool_calls=[{
                "name": "shaft_size_calculator",
                "args": {"family": "ESW", "load_kg": 450, "speed_ms": 1.5,
                         "car_width_mm": 1200, "car_depth_mm": 1200,
                         "door_type": "中分门", "counterweight": "后置"},
                "id": "tc_shaft"}])
        return AIMessage(content="REPLY: " + last_user[:60])


def test_industrial_tool_sse_chain(client, monkeypatch):
    from app.services import agent_factory
    fake = _IndustrialFake()
    monkeypatch.setattr(agent_factory, "build_chat_model",
                        lambda settings=None, model_name="": fake)
    monkeypatch.setattr(agent_factory, "build_judge_model",
                        lambda settings=None: fake)

    token, _ = signup(client, email="carol@example.com")
    agent = client.post("/api/agents", headers=auth_headers(token), json={
        "name": "井道助手",
        "tools": ["query_design_rules", "shaft_size_calculator"],
    })
    assert agent.status_code == 201, agent.text
    tid = client.post("/api/threads", headers=auth_headers(token),
                      json={"agent_id": agent.json()["id"]}).json()["id"]

    resp = client.post(f"/api/threads/{tid}/runs", headers=auth_headers(token),
                      json={"content": "ESW 450kg 1.5m/s，轿厢1200x1200，中分门，对重后置，井道要多大？"})
    assert resp.status_code == 200, resp.text
    events = parse_sse(resp.text)
    by_kind = {}
    for kind, data in events:
        by_kind.setdefault(kind, []).append(data)

    calls = [e["name"] for e in by_kind.get("tool_call", [])]
    assert "shaft_size_calculator" in calls
    results = " ".join(e.get("content", "") for e in by_kind.get("tool_result", []))
    assert "1400" in results and "1600" in results
    done = by_kind["done"][0]
    assert "1400" in done["content"]


def test_knowledge_tool_reads_seed(client):
    # Direct tool invocation relies on the seeded global DB (init_db ran).
    from app.services.industrial_tools import query_design_rules
    out = query_design_rules.invoke({"query": "井道 中分门 对重", "family": "ESW"})
    assert "《ESW 梯型井道尺寸余量规则》" in out
    empty = query_design_rules.invoke({"query": "量子隧穿电机", "family": "ESW"})
    assert "未检索到适用条款" in empty
