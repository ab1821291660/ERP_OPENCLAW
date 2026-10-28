"""Password hashing, JWT issuance/verification, API keys and RBAC dependencies."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt

from .config import get_settings
from .db import connect

ALGORITHM = "HS256"
ROLE_LEVEL = {"viewer": 1, "member": 2, "admin": 3, "owner": 4}


# ---------- password ----------
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


# ---------- JWT ----------
def create_access_token(user_id: str, tenant_id: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": user_id, "tid": tenant_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_resolved, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_resolved, algorithms=[ALGORITHM])


# ---------- API keys ----------
def generate_api_key() -> str:
    return "dap_" + secrets.token_hex(24)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(key: str) -> str:
    return key[:11] + "..."


@dataclass
class Context:
    user_id: str
    email: str
    display_name: str
    tenant_id: str
    role: str
    via_api_key: bool = False

    @property
    def is_member(self) -> bool:
        return ROLE_LEVEL[self.role] >= ROLE_LEVEL["member"]

    @property
    def is_admin(self) -> bool:
        return ROLE_LEVEL[self.role] >= ROLE_LEVEL["admin"]

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


def _context_from_jwt(token: str, db) -> Context:
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = payload.get("sub")
    tenant_id = payload.get("tid")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    row = db.execute(
        """SELECT u.id AS user_id, u.email, u.display_name, m.role
           FROM users u JOIN memberships m
             ON m.user_id = u.id AND m.tenant_id = ?
           WHERE u.id = ?""",
        (tenant_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Membership no longer exists")
    return Context(row["user_id"], row["email"], row["display_name"], tenant_id, row["role"])


def _context_from_api_key(key: str, db) -> Context:
    row = db.execute(
        """SELECT k.tenant_id, k.id AS key_id, u.id AS user_id, u.email, u.display_name
           FROM api_keys k LEFT JOIN users u ON u.id = k.created_by
           WHERE k.key_hash = ?""",
        (hash_api_key(key),),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    from .db import utcnow

    db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (utcnow(), row["key_id"]))
    db.commit()
    # API keys act with member privileges and are attributed to their creator
    return Context(
        row["user_id"] or "", row["email"] or "api-key", row["display_name"] or "API Key",
        row["tenant_id"], "member", via_api_key=True,
    )


def get_context(request: Request, authorization: str | None = Header(default=None),
                x_api_key: str | None = Header(default=None)) -> Context:
    """Resolve the caller identity from Bearer JWT or X-API-Key."""
    db = connect()
    request.state.db = db
    if authorization and authorization.lower().startswith("bearer "):
        return _context_from_jwt(authorization[7:].strip(), db)
    if x_api_key:
        return _context_from_api_key(x_api_key.strip(), db)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def require_role(*roles: str):
    """Dependency factory enforcing a minimum role."""
    needed = max(ROLE_LEVEL[r] for r in roles)

    def _dep(ctx: Context = Depends(get_context)) -> Context:
        if ROLE_LEVEL[ctx.role] < needed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return ctx

    return Depends(_dep)


def require_login(ctx: Context = Depends(get_context)) -> Context:
    return ctx


def require_member(ctx: Context = Depends(get_context)) -> Context:
    if not ctx.is_member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Membership role required")
    return ctx


def require_admin(ctx: Context = Depends(get_context)) -> Context:
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return ctx


def require_owner(ctx: Context = Depends(get_context)) -> Context:
    if not ctx.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return ctx


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
