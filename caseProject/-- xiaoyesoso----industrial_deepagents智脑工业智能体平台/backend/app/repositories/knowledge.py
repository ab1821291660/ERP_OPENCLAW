"""Data access for the global industrial knowledge base."""
from __future__ import annotations

import json


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (ValueError, TypeError):
        d["tags"] = []
    return d


def list_knowledge(db, q: str = "", family: str = "", category: str = "",
                  limit: int = 50) -> list[dict]:
    """Search knowledge rows.

    `q` whitespace-separated terms are AND-matched against title/content/tags;
    `family` / `category` are exact matches (empty = no filter).
    """
    where, params = [], []
    if family:
        where.append("family = ?")
        params.append(family.strip())
    if category:
        where.append("category = ?")
        params.append(category.strip())
    terms = [t for t in (q or "").split() if t.strip()]
    for term in terms:
        where.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
        like = f"%{term.strip()}%"
        params.extend([like, like, like])
    sql = "SELECT * FROM industrial_knowledge"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError):
        safe_limit = 50
    params.append(max(1, min(safe_limit, 200)))
    return [_row_to_dict(r) for r in db.execute(sql, params).fetchall()]


def get_knowledge_count(db) -> int:
    return db.execute("SELECT COUNT(*) c FROM industrial_knowledge").fetchone()["c"]
