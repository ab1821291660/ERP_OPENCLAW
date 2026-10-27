"""Shared API dependencies."""
from __future__ import annotations

from fastapi import Request


def get_db(request: Request):
    """Yield the request-scoped connection opened by the auth dependency."""
    db = request.state.db##===================================
    try:
        yield db
    finally:
        db.close()
