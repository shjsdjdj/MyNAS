-- MyNAS v3.1 reference schema. Runtime creation/migration lives in backend/db/database.py.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE assets (
    id TEXT PRIMARY KEY,                         -- UUID
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,                     -- display metadata only
    storage_path TEXT NOT NULL UNIQUE,           -- backend-only
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
    thumbnail_storage_path TEXT,                 -- backend-only
    exif_datetime TEXT,
    width INTEGER,
    height INTEGER,
    thumbnail_url TEXT,
    is_favorite INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_assets_user_parent ON assets(user_id,parent_id,is_deleted);
CREATE INDEX idx_assets_user_hash ON assets(user_id,hash,is_deleted);
CREATE INDEX idx_assets_user_type_created ON assets(user_id,type,created_at DESC);
CREATE INDEX idx_assets_photo_timeline ON assets(user_id,type,is_deleted,exif_datetime,created_at DESC);
CREATE INDEX idx_assets_user_favorite ON assets(user_id,is_favorite,is_deleted);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    asset_id TEXT,
    ip_address TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_audit_user_time ON audit_logs(user_id,created_at DESC);

CREATE TABLE backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    files_copied INTEGER NOT NULL DEFAULT 0,
    bytes_copied INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE backup_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_asset_id TEXT NOT NULL,
    backup_asset_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_backup_entry_source ON backup_entries(user_id,source_asset_id,created_at DESC);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE storage_locations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id,path)
);
CREATE INDEX idx_storage_user_default ON storage_locations(user_id,is_default);
