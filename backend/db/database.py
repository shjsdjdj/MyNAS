import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from backend import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_KNOWN_TABLES = frozenset({"users", "assets", "audit_logs", "backup_logs", "backup_entries", "settings", "storage_locations"})


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if table not in _KNOWN_TABLES:
        raise ValueError(f"Unknown table: {table}")
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _migrate_incompatible_assets(conn: sqlite3.Connection):
    if not _table_exists(conn, "assets"):
        return
    required = {"id", "user_id", "filename", "storage_path", "is_deleted"}
    existing = _table_columns(conn, "assets")
    if required.issubset(existing):
        if "deleted_at" not in existing:
            conn.execute("ALTER TABLE assets ADD COLUMN deleted_at TEXT")
        additions = {
            "exif_datetime": "TEXT",
            "width": "INTEGER",
            "height": "INTEGER",
            "thumbnail_url": "TEXT",
            "is_favorite": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, declaration in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE assets ADD COLUMN {column} {declaration}")
        return
    suffix = 1
    legacy_name = "assets_legacy_v1"
    while _table_exists(conn, legacy_name):
        suffix += 1
        legacy_name = f"assets_legacy_v1_{suffix}"
    conn.execute(f"ALTER TABLE assets RENAME TO {legacy_name}")


def initialize_database():
    with connection() as conn:
        _migrate_incompatible_assets(conn)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            storage_path TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL CHECK(type IN ('file','image','video','folder')),
            size INTEGER NOT NULL DEFAULT 0,
            hash TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            parent_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
            tags TEXT NOT NULL DEFAULT '[]',
            thumbnail_storage_path TEXT,
            exif_datetime TEXT,
            width INTEGER,
            height INTEGER,
            thumbnail_url TEXT,
            is_favorite INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_assets_user_parent ON assets(user_id,parent_id,is_deleted);
        CREATE INDEX IF NOT EXISTS idx_assets_user_hash ON assets(user_id,hash,is_deleted);
        CREATE INDEX IF NOT EXISTS idx_assets_user_type_created ON assets(user_id,type,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assets_photo_timeline ON assets(user_id,type,is_deleted,exif_datetime,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assets_user_favorite ON assets(user_id,is_favorite,is_deleted);

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            asset_id TEXT,
            ip_address TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id,created_at DESC);

        CREATE TABLE IF NOT EXISTS backup_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            files_copied INTEGER NOT NULL DEFAULT 0,
            bytes_copied INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            detail TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS backup_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_asset_id TEXT NOT NULL,
            backup_asset_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_backup_entry_source ON backup_entries(user_id,source_asset_id,created_at DESC);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS storage_locations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id,path)
        );
        CREATE INDEX IF NOT EXISTS idx_storage_user_default ON storage_locations(user_id,is_default);
        """)


def audit(action: str, ip_address: str, user_id: int | None = None, asset_id: str | None = None, detail: str = ""):
    # Keep the existing schema for compatibility, but never persist IPs,
    # filenames, request details, credentials, tokens, or cookies.
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs(user_id,action,asset_id,ip_address,detail,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, action[:64], None, "redacted", "", utc_now()),
        )


def recent_audit_logs(user_id: int, limit: int = 50):
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,user_id,action,asset_id,ip_address,detail,created_at FROM audit_logs "
            "WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit),
        ).fetchall()]


def all_audit_logs(limit: int = 50):
    """Return audit logs across all users (admin only)."""
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,user_id,action,asset_id,ip_address,detail,created_at FROM audit_logs "
            "ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()]


def get_setting(key: str, default: str | None = None) -> str | None:
    with connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with connection() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value),
        )


# v1-compatible activity names now write to the security audit log.
def record_activity(action: str, target: str, detail: str = ""):
    audit(action, "system", detail=f"{target} {detail}".strip())


def recent_activities(limit: int = 8):
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id,action,COALESCE(asset_id,'') AS target,detail,created_at "
            "FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()]
