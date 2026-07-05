import json
import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from backend import config
from backend.db.database import connection, utc_now
from backend.models.asset import Asset
from backend.storage.secure_storage import allocate_storage_path, validate_internal_path
from backend.utils.files import size_label

ROOT_NAMES = ("Photos", "Videos", "Documents", "Downloads", "Backup")


class AssetForbidden(Exception):
    pass


def ensure_root_folders(user_id: int):
    for name in ROOT_NAMES:
        with connection() as conn:
            row = conn.execute(
                "SELECT id FROM assets WHERE user_id=? AND parent_id IS NULL AND filename=? AND is_deleted=0",
                (user_id, name),
            ).fetchone()
        if not row:
            create_folder(user_id, name, None)


def create_folder(user_id: int, filename: str, parent_id: str | None) -> Asset:
    if parent_id:
        parent = get_owned_asset(parent_id, user_id)
        if parent.type != "folder":
            raise ValueError("父资源不是文件夹")
    asset_id = str(uuid4())
    storage = allocate_storage_path(user_id, asset_id)
    storage.mkdir(parents=True, exist_ok=False)
    now = utc_now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO assets(id,user_id,filename,storage_path,type,size,hash,created_at,updated_at,mime_type,is_deleted,parent_id,tags) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, user_id, filename, str(storage), "folder", 0, None, now, now, "inode/directory", 0, parent_id, "[]"),
        )
    return get_owned_asset(asset_id, user_id)


def create_file_asset(
    user_id: int, asset_id: str, filename: str, storage_path: Path, size: int,
    digest: str, mime_type: str, parent_id: str,
) -> Asset:
    parent = get_owned_asset(parent_id, user_id)
    if parent.type != "folder":
        raise ValueError("父资源不是文件夹")
    kind = "image" if mime_type.startswith("image/") else "video" if mime_type.startswith("video/") else "file"
    stat = storage_path.stat()
    from datetime import datetime, timezone
    created = datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
    updated = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    with connection() as conn:
        conn.execute(
            "INSERT INTO assets(id,user_id,filename,storage_path,type,size,hash,created_at,updated_at,mime_type,is_deleted,parent_id,tags) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, user_id, filename, str(storage_path), kind, size, digest, created, updated, mime_type, 0, parent_id, "[]"),
        )
    return get_owned_asset(asset_id, user_id)


def get_owned_asset(asset_id: str, user_id: int, include_deleted: bool = False) -> Asset:
    with connection() as conn:
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        raise FileNotFoundError("资产不存在")
    asset = Asset.from_row(row)
    if asset.user_id != user_id:
        raise AssetForbidden("无权访问此资产")
    if asset.is_deleted and not include_deleted:
        raise FileNotFoundError("资产不存在")
    return asset


def find_duplicate(user_id: int, digest: str) -> Asset | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND hash=? AND is_deleted=0 AND type!='folder' ORDER BY created_at LIMIT 1",
            (user_id, digest),
        ).fetchone()
    return Asset.from_row(row) if row else None


def list_assets(user_id: int, parent_id: str | None) -> dict:
    if parent_id:
        parent = get_owned_asset(parent_id, user_id)
        if parent.type != "folder":
            raise ValueError("资源不是文件夹")
    else:
        parent = None
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND parent_id IS ? AND is_deleted=0 "
            "ORDER BY type!='folder', lower(filename)", (user_id, parent_id),
        ).fetchall()
    return {
        "parent": public_asset(parent) if parent else None,
        "breadcrumbs": breadcrumbs(user_id, parent_id) if parent_id else [],
        "items": [public_asset(Asset.from_row(row)) for row in rows],
    }


def breadcrumbs(user_id: int, asset_id: str) -> list[dict]:
    chain = []
    current = get_owned_asset(asset_id, user_id)
    while current:
        chain.append({"id": current.id, "filename": current.filename})
        current = get_owned_asset(current.parent_id, user_id) if current.parent_id else None
    return list(reversed(chain))


def delete_asset(user_id: int, asset_id: str):
    asset = get_owned_asset(asset_id, user_id)
    if asset.parent_id is None:
        raise ValueError("系统根目录不可删除")
    with connection() as conn:
        conn.execute(
            "WITH RECURSIVE descendants(id) AS (SELECT id FROM assets WHERE id=? AND user_id=? UNION ALL "
            "SELECT a.id FROM assets a JOIN descendants d ON a.parent_id=d.id WHERE a.user_id=?) "
            "UPDATE assets SET is_deleted=1,deleted_at=?,updated_at=? WHERE id IN (SELECT id FROM descendants)",
            (asset_id, user_id, user_id, utc_now(), utc_now()),
        )
    return get_owned_asset(asset_id, user_id, include_deleted=True)


def restore_asset(user_id: int, asset_id: str):
    asset = get_owned_asset(asset_id, user_id, include_deleted=True)
    with connection() as conn:
        conn.execute(
            "WITH RECURSIVE descendants(id) AS (SELECT id FROM assets WHERE id=? AND user_id=? UNION ALL "
            "SELECT a.id FROM assets a JOIN descendants d ON a.parent_id=d.id WHERE a.user_id=?) "
            "UPDATE assets SET is_deleted=0,deleted_at=NULL,updated_at=? WHERE id IN (SELECT id FROM descendants)",
            (asset_id, user_id, user_id, utc_now()),
        )
    return get_owned_asset(asset_id, user_id)


def permanent_delete_asset(user_id: int, asset_id: str):
    asset = get_owned_asset(asset_id, user_id, include_deleted=True)
    if not asset.is_deleted:
        raise ValueError("只能永久删除已在回收站中的项目")
    with connection() as conn:
        rows = conn.execute(
            "WITH RECURSIVE descendants(id) AS (SELECT id FROM assets WHERE id=? AND user_id=? UNION ALL "
            "SELECT a.id FROM assets a JOIN descendants d ON a.parent_id=d.id WHERE a.user_id=?) "
            "SELECT id,storage_path,type,thumbnail_storage_path FROM assets WHERE id IN (SELECT id FROM descendants)",
            (asset_id, user_id, user_id),
        ).fetchall()
        
    for row in rows:
        storage = validate_internal_path(user_id, row["storage_path"])
        if row["type"] == "folder":
            shutil.rmtree(storage, ignore_errors=True)
        else:
            storage.unlink(missing_ok=True)
        if row["thumbnail_storage_path"]:
            thumbnail = Path(row["thumbnail_storage_path"]).resolve()
            thumbnail_root = (config.DATA_ROOT / "Thumbnails" / str(user_id)).resolve()
            if thumbnail_root in thumbnail.parents:
                thumbnail.unlink(missing_ok=True)
                
    with connection() as conn:
        conn.execute(
            "WITH RECURSIVE descendants(id) AS (SELECT id FROM assets WHERE id=? AND user_id=? UNION ALL "
            "SELECT a.id FROM assets a JOIN descendants d ON a.parent_id=d.id WHERE a.user_id=?) "
            "DELETE FROM assets WHERE id IN (SELECT id FROM descendants)",
            (asset_id, user_id, user_id),
        )
    return asset


def list_trash(user_id: int) -> list[dict]:
    with connection() as conn:
        # Select items that are deleted, and whose parents are either NOT deleted or are NULL.
        # This gives us the top-level trash items.
        rows = conn.execute(
            "SELECT a.* FROM assets a "
            "LEFT JOIN assets p ON a.parent_id = p.id "
            "WHERE a.user_id=? AND a.is_deleted=1 AND (a.parent_id IS NULL OR p.is_deleted=0 OR p.id IS NULL) "
            "ORDER BY a.deleted_at DESC", (user_id,)
        ).fetchall()
    return [public_asset(Asset.from_row(row)) for row in rows]


def empty_trash(user_id: int):
    with connection() as conn:
        rows = conn.execute(
            "SELECT a.id FROM assets a "
            "LEFT JOIN assets p ON a.parent_id = p.id "
            "WHERE a.user_id=? AND a.is_deleted=1 AND (a.parent_id IS NULL OR p.is_deleted=0 OR p.id IS NULL)",
            (user_id,)
        ).fetchall()
    deleted_ids = []
    for row in rows:
        permanent_delete_asset(user_id, row["id"])
        deleted_ids.append(row["id"])
    return deleted_ids


def dashboard_categories(user_id: int) -> list[dict]:
    output = []
    with connection() as conn:
        roots = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND parent_id IS NULL AND is_deleted=0 ORDER BY id", (user_id,)
        ).fetchall()
        for root_row in roots:
            root = Asset.from_row(root_row)
            totals = conn.execute(
                "WITH RECURSIVE tree(id,size,type) AS (SELECT id,size,type FROM assets WHERE id=? AND is_deleted=0 "
                "UNION ALL SELECT a.id,a.size,a.type FROM assets a JOIN tree t ON a.parent_id=t.id WHERE a.is_deleted=0) "
                "SELECT COUNT(CASE WHEN type!='folder' THEN 1 END) AS count, "
                "COALESCE(SUM(CASE WHEN type!='folder' THEN size ELSE 0 END),0) AS size FROM tree",
                (root.id,),
            ).fetchone()
            output.append({"id": root.id, "name": root.filename, "count": totals["count"], "size": totals["size"], "size_label": size_label(totals["size"])})
    order = {name: i for i, name in enumerate(ROOT_NAMES)}
    return sorted(output, key=lambda item: order.get(item["name"], 99))


def set_tags(user_id: int, asset_id: str, tags: list[str]) -> Asset:
    get_owned_asset(asset_id, user_id)
    clean = sorted({tag.strip() for tag in tags if tag.strip()})
    with connection() as conn:
        conn.execute("UPDATE assets SET tags=?,updated_at=? WHERE id=? AND user_id=?", (json.dumps(clean, ensure_ascii=False), utc_now(), asset_id, user_id))
    return get_owned_asset(asset_id, user_id)


def public_asset(asset: Asset | None) -> dict | None:
    if asset is None:
        return None
    return {
        "id": asset.id, "filename": asset.filename, "name": asset.filename,
        "type": asset.type, "size": asset.size, "size_label": "文件夹" if asset.type == "folder" else size_label(asset.size),
        "hash": asset.hash, "created_at": asset.created_at, "updated_at": asset.updated_at,
        "modified_at": asset.updated_at, "mime_type": asset.mime_type,
        "parent_id": asset.parent_id, "tags": asset.tags,
        "thumbnail_url": f"/api/assets/{asset.id}/thumbnail" if asset.thumbnail_storage_path else None,
        "is_directory": asset.type == "folder",
        "deleted_at": asset.deleted_at,
        "exif_datetime": asset.exif_datetime,
        "width": asset.width,
        "height": asset.height,
        "is_favorite": asset.is_favorite,
    }


def set_favorite(user_id: int, asset_id: str, desired: bool | None = None) -> Asset:
    asset = get_owned_asset(asset_id, user_id)
    if asset.type != "image":
        raise ValueError("只有照片可以收藏")
    value = (not asset.is_favorite) if desired is None else desired
    with connection() as conn:
        conn.execute(
            "UPDATE assets SET is_favorite=?,updated_at=? WHERE id=? AND user_id=?",
            (int(value), utc_now(), asset_id, user_id),
        )
    return get_owned_asset(asset_id, user_id)
