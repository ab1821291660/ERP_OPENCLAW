"""Project (formerly workspace) API, thread -> project scoping, fs isolation."""
from conftest import auth_headers, signup


def _make_agent(client, token):
    resp = client.post("/api/agents", headers=auth_headers(token),
                       json={"name": "项目助手", "tools": []})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_default_project_seeded(client):
    token, _ = signup(client)
    projects = client.get("/api/projects", headers=auth_headers(token)).json()
    assert len(projects) == 1
    assert projects[0]["name"] == "默认项目"
    assert projects[0]["slug"] == "default"
    assert projects[0]["thread_count"] == 0


def test_create_project_named_and_unnamed(client):
    token, _ = signup(client)
    named = client.post("/api/projects", headers=auth_headers(token),
                        json={"name": "像素方块世界"})
    assert named.status_code == 201
    assert named.json()["name"] == "像素方块世界"

    unnamed = client.post("/api/projects", headers=auth_headers(token), json={})
    assert unnamed.status_code == 201
    assert unnamed.json()["name"].startswith("新项目")
    assert unnamed.json()["slug"].startswith("p-")

    listed = client.get("/api/projects", headers=auth_headers(token)).json()
    assert len(listed) == 3
    assert {p["name"] for p in listed} >= {"默认项目", "像素方块世界"}


def test_thread_without_project_auto_creates_one(client):
    token, _ = signup(client)
    default_id = next(p["id"] for p in
                      client.get("/api/projects", headers=auth_headers(token)).json()
                      if p["slug"] == "default")
    agent = _make_agent(client, token)
    resp = client.post("/api/threads", headers=auth_headers(token),
                       json={"agent_id": agent["id"]})
    assert resp.status_code == 201, resp.text
    thread = resp.json()
    assert thread["project_id"] and thread["project_id"] != default_id

    projects = client.get("/api/projects", headers=auth_headers(token)).json()
    assert len(projects) == 2
    counts = {p["id"]: p["thread_count"] for p in projects}
    assert counts[default_id] == 0
    assert counts[thread["project_id"]] == 1


def test_thread_scoped_listing_and_explicit_project(client):
    token, _ = signup(client)
    project = client.post("/api/projects", headers=auth_headers(token),
                          json={"name": "项目A"}).json()
    agent = _make_agent(client, token)
    t1 = client.post("/api/threads", headers=auth_headers(token),
                     json={"agent_id": agent["id"], "project_id": project["id"]}).json()
    t2 = client.post("/api/threads", headers=auth_headers(token),
                     json={"agent_id": agent["id"]}).json()
    assert t1["project_id"] == project["id"]

    scoped = client.get(f"/api/threads?project_id={project['id']}",
                        headers=auth_headers(token)).json()
    assert [t["id"] for t in scoped] == [t1["id"]]
    assert scoped[0]["project_id"] == project["id"]

    all_threads = client.get("/api/threads", headers=auth_headers(token)).json()
    assert {t["id"] for t in all_threads} == {t1["id"], t2["id"]}


def test_cross_tenant_project_rejected_404(client):
    alice, _ = signup(client, email="alice@example.com")
    bob, _ = signup(client, email="bob@example.com", name="Bob", org="BobOrg")
    project = client.post("/api/projects", headers=auth_headers(alice),
                          json={"name": "Alice 的项目"}).json()
    agent = _make_agent(client, alice)
    resp = client.post("/api/threads", headers=auth_headers(alice),
                       json={"agent_id": agent["id"], "project_id": project["id"]})
    assert resp.status_code == 201
    # Bob cannot see or use Alice's project
    bob_projects = client.get("/api/projects", headers=auth_headers(bob)).json()
    assert project["id"] not in {p["id"] for p in bob_projects}
    bob_agent = _make_agent(client, bob)
    denied = client.post("/api/threads", headers=auth_headers(bob),
                         json={"agent_id": bob_agent["id"], "project_id": project["id"]})
    assert denied.status_code == 404
    assert "项目不存在" in denied.json()["detail"]


def test_project_fs_roots_are_isolated(platform_env, client):
    token, body = signup(client)
    tenant_id = body["user"]["tenant_id"]
    p1 = client.post("/api/projects", headers=auth_headers(token),
                     json={"name": "项目一"}).json()
    p2 = client.post("/api/projects", headers=auth_headers(token), json={}).json()
    agent = _make_agent(client, token)
    t1 = client.post("/api/threads", headers=auth_headers(token),
                     json={"agent_id": agent["id"], "project_id": p1["id"]}).json()

    fs_root = platform_env / "data" / "fs" / tenant_id
    dirs = {d.name for d in fs_root.iterdir() if d.is_dir()}
    assert dirs == {p1["id"], p2["id"]}
    # Thread auto-created project materializes its root too
    assert (fs_root / t1["project_id"]).is_dir()
