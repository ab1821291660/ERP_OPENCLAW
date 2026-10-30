"""Authentication endpoints: signup, login, current user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..models import AuthOut, LoginIn, SignupIn, TenantOut, UserOut
from ..repositories import tenants as tenant_repo
from ..security import (
    Context,
    create_access_token,
    hash_password,
    require_login,
    verify_password,
)
from ..db import _seed_industrial, connect
from .deps import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_payload(db, user, tenant_id: str, tenant_name: str, role: str) -> AuthOut:
    token = create_access_token(user["id"], tenant_id)
    tenants = [TenantOut(id=r["id"], name=r["name"], role=r["role"])
               for r in tenant_repo.list_user_tenants(db, user["id"])]
    return AuthOut(
        token=token,
        user=UserOut(
            id=user["id"], email=user["email"], display_name=user["display_name"],
            tenant_id=tenant_id, tenant_name=tenant_name, role=role,
        ),
        tenants=tenants,
    )


@router.post("/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn):
    db = connect()
    email = body.email.lower().strip()
    if tenant_repo.get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="邮箱已注册")
    user_id = tenant_repo.create_user(db, email, hash_password(body.password), body.display_name)
    org_name = body.org_name.strip() or f"{body.display_name.strip()} 的组织"
    tenant_id, _ = tenant_repo.create_tenant_with_project(db, org_name, user_id, slug_base=email.split("@")[0])
    _seed_industrial(db)
    db.commit()
    user = tenant_repo.get_user(db, user_id)
    payload = _auth_payload(db, user, tenant_id, org_name, "owner")
    db.close()
    return payload


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn):
    db = connect()
    user = tenant_repo.get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        db.close()
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    memberships = tenant_repo.list_user_tenants(db, user["id"])
    if not memberships:
        db.close()
        raise HTTPException(status_code=403, detail="用户不属于任何租户")
    current = memberships[0]
    tenant = db.execute("SELECT name FROM tenants WHERE id=?", (current["id"],)).fetchone()
    payload = _auth_payload(db, user, current["id"], tenant["name"], current["role"])
    db.close()
    return payload


@router.get("/me", response_model=AuthOut)
def me(ctx: Context = Depends(require_login), db=Depends(get_db)):
    user = tenant_repo.get_user(db, ctx.user_id)
    tenant = db.execute("SELECT name FROM tenants WHERE id=?", (ctx.tenant_id,)).fetchone()
    tenants = [TenantOut(id=r["id"], name=r["name"], role=r["role"])
               for r in tenant_repo.list_user_tenants(db, ctx.user_id)]
    return AuthOut(
        token="",
        user=UserOut(
            id=user["id"], email=user["email"], display_name=user["display_name"],
            tenant_id=ctx.tenant_id, tenant_name=tenant["name"] if tenant else "", role=ctx.role,
        ),
        tenants=tenants,
    )
