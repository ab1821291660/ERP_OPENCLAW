"""Tenant, membership and API-key endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..models import (
    ApiKeyIn,
    ApiKeyOut,
    MemberIn,
    MemberOut,
    MemberUpdateIn,
    ProjectIn,
    ProjectOut,
    SwitchIn,
    TenantCreateIn,
    TenantOut,
)
from ..repositories import tenants as repo
from ..security import (
    Context,
    create_access_token,
    generate_api_key,
    hash_api_key,
    key_prefix,
    require_admin,
    require_login,
    require_member,
    require_owner,
)
from ..services.agent_factory import project_fs_root
from .deps import get_db

router = APIRouter(tags=["tenants"])


def _member_out(db, membership_id: str) -> MemberOut:
    row = db.execute(
        """SELECT m.id, m.user_id, u.email, u.display_name, m.role, m.created_at
           FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.id=?""",
        (membership_id,),
    ).fetchone()
    return MemberOut(**dict(row))


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(ctx: Context = Depends(require_login), db=Depends(get_db)):
    return [TenantOut(id=r["id"], name=r["name"], role=r["role"])
            for r in repo.list_user_tenants(db, ctx.user_id)]


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreateIn, ctx: Context = Depends(require_login), db=Depends(get_db)):
    tid, _ = repo.create_tenant_with_project(db, body.name.strip(), ctx.user_id)
    db.commit()
    return TenantOut(id=tid, name=body.name.strip(), role="owner")


@router.post("/tenants/switch")
def switch_tenant(body: SwitchIn, ctx: Context = Depends(require_login), db=Depends(get_db)):
    membership = repo.get_membership(db, body.tenant_id, ctx.user_id)
    if not membership:
        raise HTTPException(status_code=403, detail="未加入该租户")
    tenant = db.execute("SELECT name FROM tenants WHERE id=?", (body.tenant_id,)).fetchone()
    return {"token": create_access_token(ctx.user_id, body.tenant_id),
            "tenant_id": body.tenant_id, "tenant_name": tenant["name"], "role": membership["role"]}


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(ctx: Context = Depends(require_login), db=Depends(get_db)):
    return [
        ProjectOut(
            id=r["id"], name=r["name"], slug=r["slug"], created_at=r["created_at"],
            thread_count=r["thread_count"],
        )
        for r in repo.list_projects(db, ctx.tenant_id)
    ]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, ctx: Context = Depends(require_member), db=Depends(get_db)):
    pid = repo.create_project(db, ctx.tenant_id, body.name.strip())
    # Materialize the isolated filesystem root for this project.
    project_fs_root(ctx.tenant_id, pid)
    db.commit()
    row = repo.get_project(db, pid, ctx.tenant_id)
    return ProjectOut(
        id=row["id"], name=row["name"], slug=row["slug"],
        created_at=row["created_at"], thread_count=0,
    )


@router.get("/tenants/members", response_model=list[MemberOut])
def list_members(ctx: Context = Depends(require_member), db=Depends(get_db)):
    return [MemberOut(**dict(r)) for r in repo.list_members(db, ctx.tenant_id)]


@router.post("/tenants/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, ctx: Context = Depends(require_admin), db=Depends(get_db)):
    user = repo.get_user_by_email(db, body.email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱尚未注册，请先让对方完成注册")
    if repo.get_membership(db, ctx.tenant_id, user["id"]):
        raise HTTPException(status_code=409, detail="该用户已是租户成员")
    mid = repo.add_member(db, ctx.tenant_id, user["id"], body.role)
    db.commit()
    return _member_out(db, mid)


@router.patch("/tenants/members/{membership_id}", response_model=MemberOut)
def patch_member(membership_id: str, body: MemberUpdateIn,
                 ctx: Context = Depends(require_owner), db=Depends(get_db)):
    row = db.execute(
        "SELECT * FROM memberships WHERE id=? AND tenant_id=?", (membership_id, ctx.tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    if body.role != "owner" and row["role"] == "owner" and repo.count_owners(db, ctx.tenant_id) <= 1:
        raise HTTPException(status_code=400, detail="租户必须保留至少一名 owner")
    repo.update_member_role(db, ctx.tenant_id, membership_id, body.role)
    db.commit()
    return _member_out(db, membership_id)


@router.delete("/tenants/members/{membership_id}", status_code=204)
def remove_member(membership_id: str, ctx: Context = Depends(require_owner), db=Depends(get_db)):
    row = db.execute(
        "SELECT * FROM memberships WHERE id=? AND tenant_id=?", (membership_id, ctx.tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    if row["role"] == "owner" and repo.count_owners(db, ctx.tenant_id) <= 1:
        raise HTTPException(status_code=400, detail="租户必须保留至少一名 owner")
    repo.delete_membership(db, ctx.tenant_id, membership_id)
    db.commit()


# ---------- API keys ----------
@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(ctx: Context = Depends(require_member), db=Depends(get_db)):
    return [ApiKeyOut(**dict(r)) for r in repo.list_api_keys(db, ctx.tenant_id)]


@router.post("/api-keys", response_model=ApiKeyOut, status_code=201)
def create_key(body: ApiKeyIn, ctx: Context = Depends(require_owner), db=Depends(get_db)):
    plaintext = generate_api_key()
    kid = repo.create_api_key(
        db, ctx.tenant_id, body.name.strip(), hash_api_key(plaintext),
        key_prefix(plaintext), ctx.user_id,
    )
    db.commit()
    row = db.execute(
        "SELECT id,name,key_prefix,created_at,last_used_at FROM api_keys WHERE id=?", (kid,)
    ).fetchone()
    out = ApiKeyOut(**dict(row))
    out.plaintext = plaintext
    return out


@router.delete("/api-keys/{key_id}", status_code=204)
def delete_key(key_id: str, ctx: Context = Depends(require_owner), db=Depends(get_db)):
    repo.delete_api_key(db, ctx.tenant_id, key_id)
    db.commit()
