import json
import os
import platform
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from backend import config
from backend.db.database import connection, get_setting, set_setting, utc_now
from backend.services.backup_service import backup_logs, configure_daily_schedule
from backend.utils.files import size_label

MYNAS_VERSION = "3.1.0"
DEFAULT_PREFERENCES = {
    "language": "zh",
    "theme": "light",
    "default_home": "photos",
    "default_upload_directory": "Photos",
    "photo_sort": "taken_desc",
}


def ensure_default_storage(user_id: int):
    with connection() as conn:
        exists = conn.execute("SELECT 1 FROM storage_locations WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
        if not exists:
            now = utc_now()
            conn.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                (str(uuid4()), user_id, "Main Storage", str(config.DATA_ROOT), now, now),
            )


def get_preferences(user_id: int) -> dict:
    raw = get_setting(f"preferences_{user_id}")
    try:
        saved = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        saved = {}
    return {**DEFAULT_PREFERENCES, **saved}


def update_preferences(user_id: int, changes: dict) -> dict:
    preferences = get_preferences(user_id)
    allowed = {
        "language": {"zh", "en"},
        "theme": {"light", "dark"},
        "default_home": {"photos", "timeline", "recent", "dashboard"},
        "default_upload_directory": {"Photos", "Videos", "Documents", "Downloads", "Backup"},
        "photo_sort": {"taken_desc", "taken_asc", "uploaded_desc"},
    }
    for key, value in changes.items():
        if value is not None:
            if value not in allowed[key]:
                raise ValueError(f"Invalid preference: {key}")
            preferences[key] = value
    set_setting(f"preferences_{user_id}", json.dumps(preferences, ensure_ascii=False))
    return preferences


def list_storage_locations(user_id: int) -> list[dict]:
    ensure_default_storage(user_id)
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM storage_locations WHERE user_id=? ORDER BY is_default DESC,created_at", (user_id,)
        ).fetchall()
    return [_storage_public(dict(row)) for row in rows]


def create_storage_location(user_id: int, name: str, path: str, is_default: bool = False) -> dict:
    clean_path = validate_storage_path(path)
    location_id, now = str(uuid4()), utc_now()
    with connection() as conn:
        if is_default:
            conn.execute("UPDATE storage_locations SET is_default=0 WHERE user_id=?", (user_id,))
        try:
            conn.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (location_id, user_id, name.strip(), clean_path, int(is_default), now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Storage location already exists") from exc
    return get_storage_location(user_id, location_id)


def update_storage_location(user_id: int, location_id: str, name: str | None, path: str | None) -> dict:
    current = get_storage_location(user_id, location_id)
    next_name = name.strip() if name is not None else current["name"]
    next_path = validate_storage_path(path) if path is not None else current["path"]
    with connection() as conn:
        try:
            conn.execute(
                "UPDATE storage_locations SET name=?,path=?,updated_at=? WHERE id=? AND user_id=?",
                (next_name, next_path, utc_now(), location_id, user_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Storage location already exists") from exc
    return get_storage_location(user_id, location_id)


def delete_storage_location(user_id: int, location_id: str):
    location = get_storage_location(user_id, location_id)
    if location["is_default"]:
        raise ValueError("Set another default storage before deleting this location")
    with connection() as conn:
        conn.execute("DELETE FROM storage_locations WHERE id=? AND user_id=?", (location_id, user_id))


def set_default_storage(user_id: int, location_id: str) -> dict:
    get_storage_location(user_id, location_id)
    with connection() as conn:
        conn.execute("UPDATE storage_locations SET is_default=0 WHERE user_id=?", (user_id,))
        conn.execute(
            "UPDATE storage_locations SET is_default=1,updated_at=? WHERE id=? AND user_id=?",
            (utc_now(), location_id, user_id),
        )
    return get_storage_location(user_id, location_id)


def get_storage_location(user_id: int, location_id: str) -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM storage_locations WHERE id=? AND user_id=?", (location_id, user_id)
        ).fetchone()
    if not row:
        raise FileNotFoundError("Storage location not found")
    return _storage_public(dict(row))


def validate_storage_path(path: str) -> str:
    clean = path.strip().rstrip("\\/")
    if not re.fullmatch(r"[A-Za-z]:\\(?:[^<>:\"|?*\\/]+\\?)*", clean + ("\\" if clean.endswith(":") else "")):
        if not re.fullmatch(r"[A-Za-z]:\\.*", clean):
            raise ValueError("Storage path must be an absolute Windows drive path")
    if ".." in Path(clean).parts:
        raise ValueError("Storage path traversal is not allowed")
    return clean


def backup_settings(user_id: int) -> dict:
    raw = get_setting(f"backup_daily_{user_id}")
    try:
        saved = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        saved = {}
    logs = backup_logs(user_id, 1)
    return {
        "directory": get_setting(f"backup_directory_{user_id}", str(config.DATA_ROOT / "Backup")),
        "enabled": bool(saved.get("enabled", False)),
        "daily_time": saved.get("daily_time", "02:00"),
        "last_backup_at": logs[0]["finished_at"] if logs else None,
        "last_status": logs[0]["status"] if logs else "never",
    }


def update_backup_settings(user_id: int, directory: str | None, enabled: bool | None, daily_time: str | None) -> dict:
    current = backup_settings(user_id)
    next_directory = validate_storage_path(directory) if directory is not None else current["directory"]
    next_enabled = enabled if enabled is not None else current["enabled"]
    next_time = daily_time or current["daily_time"]
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", next_time):
        raise ValueError("daily_time must use HH:MM")
    set_setting(f"backup_directory_{user_id}", next_directory)
    configure_daily_schedule(user_id, next_time, next_enabled)
    return backup_settings(user_id)


def system_information(user_id: int) -> dict:
    with connection() as conn:
        counts = conn.execute(
            "SELECT COUNT(*) asset_count, SUM(type='image') photo_count, SUM(type='video') video_count, "
            "SUM(type='file') file_count, SUM(is_favorite=1) favorite_count FROM assets WHERE user_id=? AND is_deleted=0",
            (user_id,),
        ).fetchone()
    db_size = config.DATABASE_PATH.stat().st_size if config.DATABASE_PATH.exists() else 0
    thumbnail_root = config.DATA_ROOT / "Thumbnails" / str(user_id)
    thumbnail_size = sum(path.stat().st_size for path in thumbnail_root.rglob("*") if path.is_file()) if thumbnail_root.exists() else 0
    disk = shutil.disk_usage(config.DATA_ROOT)
    return {
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "mynas_version": MYNAS_VERSION,
        "database_size": db_size,
        "database_size_label": size_label(db_size),
        "thumbnail_cache_size": thumbnail_size,
        "thumbnail_cache_size_label": size_label(thumbnail_size),
        "asset_count": counts["asset_count"] or 0,
        "photo_count": counts["photo_count"] or 0,
        "video_count": counts["video_count"] or 0,
        "file_count": counts["file_count"] or 0,
        "favorite_count": counts["favorite_count"] or 0,
        "storage_usage": {"used": disk.used, "total": disk.total, "free": disk.free, "percent": round(disk.used / disk.total * 100, 1)},
    }


def _storage_public(row: dict) -> dict:
    path = Path(row["path"])
    capacity = {"available": False, "total": 0, "used": 0, "free": 0, "percent": 0}
    if path.exists():
        usage = shutil.disk_usage(path)
        capacity = {
            "available": True,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1),
            "total_label": size_label(usage.total),
            "free_label": size_label(usage.free),
        }
    return {**row, "is_default": bool(row["is_default"]), "capacity": capacity}
