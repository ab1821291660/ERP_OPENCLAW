"""Data access for users, tenants, projects, memberships and API keys."""
from __future__ import annotations

from ..db import utcnow
from ..util import new_id, slugify, unique_slug


def create_user(db, email: str, password_hash: str, display_name: str) -> str:
    uid = new_id()
    db.execute(
        "INSERT INTO users(id,email,password_hash,display_name,created_at) VALUES(?,?,?,?,?)",
        (uid, email.lower().strip(), password_hash, display_name, utcnow()),
    )
    return uid


def get_user_by_email(db, email: str):
    return db.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()


def get_user(db, user_id: str):
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_user_tenants(db, user_id: str):
    return db.execute(
        """SELECT t.id, t.name, m.role FROM tenants t
           JOIN memberships m ON m.tenant_id = t.id
           WHERE m.user_id = ? ORDER BY t.created_at""",
        (user_id,),
    ).fetchall()


def create_tenant_with_project(db, name: str, user_id: str, slug_base: str | None = None):
    """Create tenant + default project + owner membership atomically."""
    now = utcnow()
    tid, pid = new_id(), new_id()
    base = slugify(slug_base or name)
    slug = unique_slug(base, lambda s: db.execute("SELECT 1 FROM tenants WHERE slug=?", (s,)).fetchone())
    db.execute("INSERT INTO tenants(id,name,slug,created_at) VALUES(?,?,?,?)", (tid, name, slug, now))
    db.execute(
        "INSERT INTO projects(id,tenant_id,name,slug,created_at) VALUES(?,?,?,?,?)",
        (pid, tid, "默认项目", "default", now),
    )
    db.execute(
        "INSERT INTO memberships(id,tenant_id,user_id,role,created_at) VALUES(?,?,?,?,?)",
        (new_id(), tid, user_id, "owner", now),
    )
    return tid, pid


def get_default_project(db, tenant_id: str):
    return db.execute(
        "SELECT * FROM projects WHERE tenant_id=? AND slug='default'", (tenant_id,)
    ).fetchone()


def get_project(db, project_id: str, tenant_id: str):
    return db.execute(
        "SELECT * FROM projects WHERE id=? AND tenant_id=?", (project_id, tenant_id)
    ).fetchone()


def create_project(db, tenant_id: str, name: str = "") -> str:
    """Insert a project row and return its id. Slug is derived from the id
    so it stays unique within the tenant without extra round-trips."""
    pid = new_id()
    now = utcnow()
    label = name.strip() or f"新项目 {pid[:8]}"
    db.execute(
        "INSERT INTO projects(id,tenant_id,name,slug,created_at) VALUES(?,?,?,?,?)",
        (pid, tenant_id, label, f"p-{pid[:12]}", now),
    )
    return pid


def list_projects(db, tenant_id: str):
    return db.execute(
        """SELECT p.*, COUNT(t.id) AS thread_count
           FROM projects p
           LEFT JOIN threads t ON t.project_id = p.id
           WHERE p.tenant_id=?
           GROUP BY p.id
           ORDER BY p.created_at DESC""",
        (tenant_id,),
    ).fetchall()


def get_membership(db, tenant_id: str, user_id: str):
    return db.execute(
        "SELECT * FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, user_id)
    ).fetchone()


def list_members(db, tenant_id: str):
    return db.execute(
        """SELECT m.id, m.user_id, u.email, u.display_name, m.role, m.created_at
           FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.tenant_id=? ORDER BY m.created_at""",
        (tenant_id,),
    ).fetchall()


def add_member(db, tenant_id: str, user_id: str, role: str) -> str:
    mid = new_id()
    db.execute(
        "INSERT INTO memberships(id,tenant_id,user_id,role,created_at) VALUES(?,?,?,?,?)",
        (mid, tenant_id, user_id, role, utcnow()),
    )
    return mid


def update_member_role(db, tenant_id: str, membership_id: str, role: str):
    db.execute("UPDATE memberships SET role=? WHERE id=? AND tenant_id=?", (role, membership_id, tenant_id))


def delete_membership(db, tenant_id: str, membership_id: str):
    db.execute("DELETE FROM memberships WHERE id=? AND tenant_id=?", (membership_id, tenant_id))


def count_owners(db, tenant_id: str) -> int:
    return db.execute(
        "SELECT COUNT(*) c FROM memberships WHERE tenant_id=? AND role='owner'", (tenant_id,)
    ).fetchone()["c"]


# ---------- API keys ----------
def create_api_key(db, tenant_id: str, name: str, key_hash: str, prefix: str, created_by: str):
    kid = new_id()
    db.execute(
        """INSERT INTO api_keys(id,tenant_id,name,key_hash,key_prefix,created_by,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (kid, tenant_id, name, key_hash, prefix, created_by or None, utcnow()),
    )
    return kid


def list_api_keys(db, tenant_id: str):
    return db.execute(
        "SELECT id,name,key_prefix,created_at,last_used_at FROM api_keys WHERE tenant_id=? ORDER BY created_at DESC",
        (tenant_id,),
    ).fetchall()


def delete_api_key(db, tenant_id: str, key_id: str):
    db.execute("DELETE FROM api_keys WHERE id=? AND tenant_id=?", (key_id, tenant_id))
