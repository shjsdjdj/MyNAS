import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler

from backend import config
from backend.db.database import audit, connection, get_setting, set_setting, utc_now
from backend.models.asset import Asset
from backend.storage.secure_storage import validate_internal_path
from backend.utils.files import sha256_file

scheduler = BackgroundScheduler(daemon=True)


def run_incremental_backup(user_id: int, ip_address: str = "scheduler") -> dict:
    started = utc_now()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO backup_logs(user_id,status,started_at) VALUES(?,?,?)", (user_id, "running", started)
        )
        log_id = cursor.lastrowid
    copied = 0
    bytes_copied = 0
    stage = None
    final_snapshot = None
    try:
        backup_root = backup_destination(user_id)
        user_root = backup_root / str(user_id)
        user_root.mkdir(parents=True, exist_ok=True)
        sources = _source_assets(user_id)
        _refresh_source_hashes(user_id, sources)
        changed = [asset for asset in sources if _needs_backup(user_id, asset)]
        snapshot_name = started[:19].replace(":", "-") + f"-{uuid4().hex[:8]}"
        entries: list[tuple[str, str, str, str]] = []
        if changed:
            stage = user_root / f".{snapshot_name}.tmp"
            final_snapshot = user_root / snapshot_name
            stage.mkdir(parents=False, exist_ok=False)
        for source in changed:
            source_path = validate_internal_path(user_id, source.storage_path)
            backup_id = str(uuid4())
            destination = stage / backup_id
            shutil.copy2(source_path, destination)
            copied_hash = sha256_file(destination)
            if copied_hash != source.hash:
                raise OSError(f"Backup integrity check failed for asset {source.id}")
            relative_backup_id = f"{snapshot_name}/{backup_id}"
            entries.append((source.id, relative_backup_id, source.hash or "", utc_now()))
            copied += 1
            bytes_copied += source.size

        if changed:
            manifest = {
                "created_at": started,
                "files": [
                    {"source_asset_id": source_id, "backup_file": backup_id, "sha256": digest}
                    for source_id, backup_id, digest, _created_at in entries
                ],
            }
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(stage, final_snapshot)
            stage = None

        with connection() as conn:
            conn.executemany(
                "INSERT INTO backup_entries(user_id,source_asset_id,backup_asset_id,source_hash,created_at) "
                "VALUES(?,?,?,?,?)",
                [(user_id, *entry) for entry in entries],
            )
            conn.execute(
                "UPDATE backup_logs SET status='completed',files_copied=?,bytes_copied=?,finished_at=? WHERE id=?",
                (copied, bytes_copied, utc_now(), log_id),
            )
        try:
            audit("backup", ip_address, user_id, detail=f"{copied} files")
        except Exception:
            # Audit persistence must not turn a verified, committed snapshot
            # into a false backup failure.
            pass
        return {"id": log_id, "status": "completed", "files_copied": copied, "bytes_copied": bytes_copied}
    except Exception as exc:
        if stage and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if final_snapshot and final_snapshot.exists():
            shutil.rmtree(final_snapshot, ignore_errors=True)
        with connection() as conn:
            conn.execute("UPDATE backup_logs SET status='failed',detail=?,finished_at=? WHERE id=?", (str(exc), utc_now(), log_id))
        audit("backup_failed", ip_address, user_id, detail=str(exc)[:500])
        raise


def backup_logs(user_id: int, limit: int = 50) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM backup_logs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()]


def configure_schedule(user_id: int, interval_minutes: int, enabled: bool) -> dict:
    value = json.dumps({"user_id": user_id, "interval_minutes": interval_minutes, "enabled": enabled})
    set_setting(f"backup_schedule_{user_id}", value)
    job_id = f"backup_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if enabled:
        scheduler.add_job(run_incremental_backup, "interval", minutes=interval_minutes, args=[user_id], id=job_id, replace_existing=True)
    return {"user_id": user_id, "interval_minutes": interval_minutes, "enabled": enabled}


def configure_daily_schedule(user_id: int, daily_time: str, enabled: bool) -> dict:
    hour, minute = (int(part) for part in daily_time.split(":", 1))
    value = json.dumps({"user_id": user_id, "daily_time": daily_time, "enabled": enabled})
    set_setting(f"backup_daily_{user_id}", value)
    job_id = f"backup_daily_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if enabled:
        scheduler.add_job(
            run_incremental_backup, "cron", hour=hour, minute=minute,
            args=[user_id], id=job_id, replace_existing=True,
        )
    return {"user_id": user_id, "daily_time": daily_time, "enabled": enabled}


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
    with connection() as conn:
        rows = conn.execute("SELECT value FROM settings WHERE key LIKE 'backup_schedule_%'").fetchall()
    for row in rows:
        try:
            config_data = json.loads(row["value"])
            configure_schedule(**config_data)
        except (ValueError, TypeError, KeyError):
            continue
    with connection() as conn:
        daily_rows = conn.execute("SELECT value FROM settings WHERE key LIKE 'backup_daily_%'").fetchall()
    for row in daily_rows:
        try:
            config_data = json.loads(row["value"])
            configure_daily_schedule(**config_data)
        except (ValueError, TypeError, KeyError):
            continue


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def validate_backup_destination(path: str) -> Path:
    destination = Path(path).resolve()
    internal = config.DATA_ROOT.resolve()
    if destination == internal or internal in destination.parents or destination in internal.parents:
        raise ValueError("Backup directory must be outside the MyNAS storage tree")
    return destination


def backup_destination(user_id: int) -> Path:
    default = config.DATA_ROOT.parent / "MyNAS-Backup"
    configured = get_setting(f"backup_directory_{user_id}", str(default))
    return validate_backup_destination(configured)


def _source_assets(user_id: int) -> list[Asset]:
    with connection() as conn:
        rows = conn.execute(
            "WITH RECURSIVE tree(id,root_name) AS ("
            "SELECT id,filename FROM assets WHERE user_id=? AND parent_id IS NULL AND is_deleted=0 "
            "UNION ALL SELECT a.id,t.root_name FROM assets a JOIN tree t ON a.parent_id=t.id WHERE a.user_id=? AND a.is_deleted=0) "
            "SELECT a.* FROM assets a JOIN tree t ON a.id=t.id WHERE a.user_id=? AND a.type!='folder' "
            "AND a.is_deleted=0 AND t.root_name!='Backup' AND a.hash IS NOT NULL",
            (user_id, user_id, user_id),
        ).fetchall()
    return [Asset.from_row(row) for row in rows]


def _needs_backup(user_id: int, asset: Asset) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT source_hash,backup_asset_id FROM backup_entries "
            "WHERE user_id=? AND source_asset_id=? ORDER BY id DESC LIMIT 1",
            (user_id, asset.id),
        ).fetchone()
    if not row or row["source_hash"] != asset.hash:
        return True
    backup_file = _backup_entry_path(user_id, row["backup_asset_id"])
    if backup_file is None:
        return True
    try:
        return not backup_file.is_file() or sha256_file(backup_file) != asset.hash
    except OSError:
        return True


def _backup_entry_path(user_id: int, relative_value: str) -> Path | None:
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    user_root = (backup_destination(user_id) / str(user_id)).resolve()
    candidate = (user_root / relative).resolve()
    if user_root not in candidate.parents:
        return None
    return candidate


def _refresh_source_hashes(user_id: int, assets: list[Asset]):
    """Trust the secure storage bytes, not a stale database hash."""
    for asset in assets:
        path = validate_internal_path(user_id, asset.storage_path)
        if not path.is_file():
            raise FileNotFoundError(f"Asset file missing: {asset.id}")
        actual_hash = sha256_file(path)
        if actual_hash != asset.hash:
            with connection() as conn:
                conn.execute(
                    "UPDATE assets SET hash=?,size=?,updated_at=? WHERE id=? AND user_id=?",
                    (actual_hash, path.stat().st_size, utc_now(), asset.id, user_id),
                )
            asset.hash = actual_hash
            asset.size = path.stat().st_size
