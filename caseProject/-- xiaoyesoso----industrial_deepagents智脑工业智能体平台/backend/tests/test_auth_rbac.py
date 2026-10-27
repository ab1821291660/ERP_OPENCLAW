"""Auth bootstrap, login, JWT, RBAC matrix and API-key access."""
from conftest import auth_headers, parse_sse, signup


def test_signup_bootstraps_tenant_owner_project(client):
    token, body = signup(client)
    assert body["user"]["role"] == "owner"
    assert body["tenants"][0]["role"] == "owner"
    projects = client.get("/api/projects", headers=auth_headers(token))
    assert projects.status_code == 200
    assert projects.json()[0]["slug"] == "default"
    assert projects.json()[0]["name"] == "默认项目"


def test_duplicate_signup_conflict(client):
    signup(client)
    resp = client.post("/api/auth/signup", json={
        "email": "alice@example.com", "password": "secret123", "display_name": "Alice2"})
    assert resp.status_code == 409


def test_login_ok_and_bad_password(client):
    signup(client)
    ok = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    assert ok.status_code == 200 and ok.json()["token"]
    bad = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    assert bad.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/agents").status_code == 401
    assert client.get("/api/agents", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_rbac_viewer_cannot_create_agent_or_thread(client):
    alice, _ = signup(client, email="alice@example.com")
    bob, _ = signup(client, email="bob@example.com", name="Bob", org="BobOrg")

    # Alice (owner of Acme) adds Bob as a viewer in Acme
    add = client.post("/api/tenants/members", headers=auth_headers(alice),
                      json={"email": "bob@example.com", "role": "viewer"})
    assert add.status_code == 201

    # Bob switches into Acme
    acme_id = add.json()  # need tenant id: fetch alice's me
    me = client.get("/api/auth/me", headers=auth_headers(alice)).json()
    acme = me["user"]["tenant_id"]
    sw = client.post("/api/tenants/switch", headers=auth_headers(bob), json={"tenant_id": acme})
    assert sw.status_code == 200
    bob_in_acme = sw.json()["token"]

    # Alice creates an agent that Bob can see but not modify
    created = client.post("/api/agents", headers=auth_headers(alice),
                          json={"name": "测试专家", "tools": ["calculate"]})
    assert created.status_code == 201

    assert client.post("/api/agents", headers=auth_headers(bob_in_acme),
                       json={"name": "X"}).status_code == 403
    agents = client.get("/api/agents", headers=auth_headers(bob_in_acme)).json()
    assert client.post("/api/threads", headers=auth_headers(bob_in_acme),
                       json={"agent_id": agents[0]["id"]}).status_code == 403
    # Viewer can read
    assert client.get("/api/agents", headers=auth_headers(bob_in_acme)).status_code == 200


def test_member_can_run_but_not_manage_members(client):
    alice, _ = signup(client, email="alice@example.com")
    bob, _ = signup(client, email="bob@example.com", name="Bob", org="BobOrg")
    me = client.get("/api/auth/me", headers=auth_headers(alice)).json()
    acme = me["user"]["tenant_id"]
    client.post("/api/tenants/members", headers=auth_headers(alice),
                json={"email": "bob@example.com", "role": "member"})
    sw = client.post("/api/tenants/switch", headers=auth_headers(bob), json={"tenant_id": acme})
    bob_in_acme = sw.json()["token"]

    # Member cannot manage members
    carol, _ = signup(client, email="carol@example.com", name="Carol", org="CarolOrg")
    assert client.post("/api/tenants/members", headers=auth_headers(bob_in_acme),
                       json={"email": "carol@example.com", "role": "viewer"}).status_code == 403


def test_switch_to_foreign_tenant_forbidden(client):
    alice, _ = signup(client, email="alice@example.com")
    bob, _ = signup(client, email="bob@example.com", name="Bob", org="BobOrg")
    acme = client.get("/api/auth/me", headers=auth_headers(alice)).json()["user"]["tenant_id"]
    assert client.post("/api/tenants/switch", headers=auth_headers(bob),
                       json={"tenant_id": acme}).status_code == 403


def test_add_unregistered_email_404(client):
    alice, _ = signup(client)
    resp = client.post("/api/tenants/members", headers=auth_headers(alice),
                       json={"email": "ghost@example.com", "role": "member"})
    assert resp.status_code == 404


def test_last_owner_protection(client):
    alice, _ = signup(client)
    members = client.get("/api/tenants/members", headers=auth_headers(alice)).json()
    assert len(members) == 1
    # Demoting the only owner is rejected
    resp = client.patch(f"/api/tenants/members/{members[0]['id']}",
                        headers=auth_headers(alice), json={"role": "member"})
    assert resp.status_code == 400
    assert client.delete(f"/api/tenants/members/{members[0]['id']}",
                         headers=auth_headers(alice)).status_code == 400


def test_api_key_lifecycle_and_single_plaintext(client):
    alice, _ = signup(client)
    created = client.post("/api/api-keys", headers=auth_headers(alice), json={"name": "ci"})
    assert created.status_code == 201
    plaintext = created.json()["plaintext"]
    assert plaintext and plaintext.startswith("dap_")

    listed = client.get("/api/api-keys", headers=auth_headers(alice)).json()
    assert listed[0]["plaintext"] is None
    assert plaintext not in str(listed)

    # Call an authenticated endpoint with X-API-Key
    ok = client.get("/api/agents", headers={"X-API-Key": plaintext})
    assert ok.status_code == 200
    used = client.get("/api/api-keys", headers=auth_headers(alice)).json()[0]
    assert used["last_used_at"] is not None

    # Viewer-role-equivalent restriction: API key acts as member -> cannot add members
    forbidden = client.post("/api/tenants/members", headers={"X-API-Key": plaintext},
                            json={"email": "x@y.com", "role": "member"})
    assert forbidden.status_code == 403

    assert client.delete(f"/api/api-keys/{listed[0]['id']}",
                         headers=auth_headers(alice)).status_code == 204
    assert client.get("/api/agents", headers={"X-API-Key": plaintext}).status_code == 401


def test_demo_seed_account(client):
    resp = client.post("/api/auth/login", json={"email": "demo@local", "password": "demo1234"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["display_name"] == "Demo User"
    agents = client.get("/api/agents", headers=auth_headers(data["token"])).json()
    assert any(a["name"] == "日常办公助手" for a in agents)
