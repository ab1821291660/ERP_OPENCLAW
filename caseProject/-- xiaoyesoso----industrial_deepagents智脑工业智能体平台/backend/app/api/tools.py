"""Tool catalog endpoint (harness tools, platform tools, capability switches)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..security import Context, require_login
from ..services.builtin_tools import tool_catalog
from .deps import get_db

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
def list_tools(ctx: Context = Depends(require_login), db=Depends(get_db)):
    return tool_catalog()
