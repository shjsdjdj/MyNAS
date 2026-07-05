from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from backend.db.database import connection
from backend.models.asset import Asset
from backend.services.asset_service import public_asset

TAKEN_AT_SQL = "COALESCE(NULLIF(exif_datetime,''), created_at)"


def photos_page(
    user_id: int,
    page: int = 1,
    page_size: int = 40,
    *,
    favorite_only: bool = False,
    recent: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    clauses = ["user_id=?", "type='image'", "is_deleted=0"]
    params: list = [user_id]
    if favorite_only:
        clauses.append("is_favorite=1")
    if date_from:
        clauses.append(f"{TAKEN_AT_SQL} >= ?")
        params.append(f"{date_from}T00:00:00" if len(date_from) == 10 else date_from)
    if date_to:
        clauses.append(f"{TAKEN_AT_SQL} <= ?")
        params.append(f"{date_to}T23:59:59" if len(date_to) == 10 else date_to)
    where = " AND ".join(clauses)
    order = "created_at" if recent else TAKEN_AT_SQL
    offset = (page - 1) * page_size
    with connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM assets WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM assets WHERE {where} ORDER BY {order} DESC,id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    items = [_photo_public(Asset.from_row(row)) for row in rows]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": offset + len(items) < total,
    }


def timeline_page(
    user_id: int,
    page: int = 1,
    page_size: int = 60,
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    if period:
        today = datetime.now(timezone.utc).date()
        if period == "today":
            date_from = date_to = today.isoformat()
        elif period == "7d":
            date_from = (today - timedelta(days=6)).isoformat()
            date_to = today.isoformat()
        else:
            raise ValueError("period 仅支持 today 或 7d")
    result = photos_page(user_id, page, page_size, date_from=date_from, date_to=date_to)
    groups: OrderedDict[str, list] = OrderedDict()
    for item in result.pop("items"):
        day = item["taken_at"][:10]
        groups.setdefault(day, []).append(item)
    result["groups"] = [
        {
            "date": day,
            "year": day[:4],
            "month": day[5:7],
            "day": day[8:10],
            "items": items,
        }
        for day, items in groups.items()
    ]
    return result


def search(
    user_id: int,
    query: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 40,
) -> dict:
    clauses = ["user_id=?", "type='image'", "is_deleted=0"]
    params: list = [user_id]
    if query:
        clauses.append("(lower(filename) LIKE ? OR lower(tags) LIKE ?)")
        pattern = f"%{query.lower()}%"
        params.extend([pattern, pattern])
    if date_from:
        clauses.append(f"{TAKEN_AT_SQL} >= ?")
        params.append(f"{date_from}T00:00:00")
    if date_to:
        clauses.append(f"{TAKEN_AT_SQL} <= ?")
        params.append(f"{date_to}T23:59:59")
    where = " AND ".join(clauses)
    offset = (page - 1) * page_size
    with connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM assets WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM assets WHERE {where} ORDER BY {TAKEN_AT_SQL} DESC,id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    items = [_photo_public(Asset.from_row(row)) for row in rows]
    return {"items": items, "page": page, "page_size": page_size, "total": total, "has_more": offset + len(items) < total}


def _photo_public(asset: Asset) -> dict:
    item = public_asset(asset)
    item["taken_at"] = asset.exif_datetime or asset.created_at
    return item
