import mimetypes
import shutil
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from backend import config
from backend.db.database import connection
from backend.services.asset_service import (
    create_file_asset, create_folder, ensure_root_folders, get_owned_asset,
)
from backend.services.thumbnail_service import generate_thumbnail
from backend.storage.secure_storage import allocate_storage_path
from backend.utils.files import sha256_file

import json
import logging
import threading
import time

from backend.db.database import audit, get_setting, set_setting, utc_now


_scan_lock = threading.Lock()
_running_scans: set[int] = set()


def start_background_scan(user_id: int, location_id: str) -> dict:
    """Start one registered-storage scan per user without accepting a request path."""
    with connection() as conn:
        location = conn.execute(
            "SELECT id,path FROM storage_locations WHERE id=? AND user_id=?",
            (location_id, user_id),
        ).fetchone()
    if not location:
        raise FileNotFoundError("Storage location not found")

    source_root = Path(location["path"])
    if not source_root.is_dir():
        return {
            "scan_started": False,
            "scan_required": True,
            "message": "Storage saved, but the path is not currently available",
        }

    resolved_root = source_root.resolve()
    internal_root = config.DATA_ROOT.resolve()
    if resolved_root == internal_root or internal_root in resolved_root.parents:
        return {
            "scan_started": False,
            "scan_required": False,
            "message": "This path is managed by the existing MyNAS scanner",
        }

    with _scan_lock:
        if user_id in _running_scans:
            return {
                "scan_started": False,
                "scan_required": True,
                "message": "A storage scan is already running",
            }
        _running_scans.add(user_id)

    thread = threading.Thread(
        target=_run_registered_storage_scan,
        args=(user_id, location_id),
        name=f"mynas-storage-scan-{user_id}",
        daemon=True,
    )
    thread.start()
    return {
        "scan_started": True,
        "scan_required": False,
        "message": "Storage scan started",
    }


def start_default_storage_scan(user_id: int) -> dict:
    """Resume automatic indexing for the user's configured default storage."""
    with connection() as conn:
        location = conn.execute(
            "SELECT id FROM storage_locations WHERE user_id=? AND is_default=1 LIMIT 1",
            (user_id,),
        ).fetchone()
    if not location:
        return {
            "scan_started": False,
            "scan_required": False,
            "message": "No default storage is configured",
        }
    return start_background_scan(user_id, location["id"])


def _run_registered_storage_scan(user_id: int, location_id: str):
    try:
        result = _scan_registered_storage(user_id, location_id)
        set_setting(
            f"storage_scan_{location_id}",
            json.dumps({"status": "completed", "finished_at": utc_now(), **result}),
        )
        audit("storage_scan", "local", user_id, detail=json.dumps(result))
    except Exception as exc:
        set_setting(
            f"storage_scan_{location_id}",
            json.dumps({"status": "failed", "finished_at": utc_now(), "error": str(exc)}),
        )
        logging.getLogger("mynas.scanner").exception("Storage scan failed")
    finally:
        with _scan_lock:
            _running_scans.discard(user_id)


def _scan_registered_storage(user_id: int, location_id: str) -> dict:
    with connection() as conn:
        location = conn.execute(
            "SELECT id,name,path FROM storage_locations WHERE id=? AND user_id=?",
            (location_id, user_id),
        ).fetchone()
    if not location:
        raise FileNotFoundError("Storage location not found")

    source_root = Path(location["path"]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError("Storage path is not available")

    root_asset = _find_or_create_root_folder(user_id, location["name"])
    parent_map: dict[Path, str] = {source_root: root_asset.id}
    imported = 0
    skipped = 0
    errors: list[dict] = []

    for source in sorted(source_root.rglob("*"), key=lambda p: (len(p.parts), str(p).lower())):
        asset_id = None
        destination = None
        try:
            parent_id = parent_map[source.parent]
            if source.is_dir():
                folder = _find_or_create_folder(user_id, parent_id, source.name)
                parent_map[source] = folder.id
                continue

            relative_path = source.relative_to(source_root).as_posix().lower()
            asset_id = str(uuid5(UUID(location_id), relative_path))
            with connection() as conn:
                existing = conn.execute(
                    "SELECT type,storage_path,thumbnail_storage_path FROM assets "
                    "WHERE id=? AND user_id=? AND is_deleted=0",
                    (asset_id, user_id),
                ).fetchone()
            if existing:
                if existing["type"] == "image" and not existing["thumbnail_storage_path"]:
                    try:
                        generate_thumbnail(asset_id, user_id, Path(existing["storage_path"]))
                    except Exception:
                        pass
                skipped += 1
                continue

            mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            digest = sha256_file(source)
            destination = allocate_storage_path(user_id, asset_id)
            shutil.copy2(source, destination)
            asset = create_file_asset(
                user_id, asset_id, source.name, destination, destination.stat().st_size,
                digest, mime, parent_id,
            )
            if asset.type == "image":
                try:
                    generate_thumbnail(asset.id, user_id, destination)
                except Exception:
                    pass
            imported += 1
        except Exception as exc:
            if asset_id:
                with connection() as conn:
                    conn.execute("DELETE FROM assets WHERE id=? AND user_id=?", (asset_id, user_id))
            if destination:
                destination.unlink(missing_ok=True)
            errors.append({"name": source.name, "error": str(exc)})

    return {"imported": imported, "skipped_existing": skipped, "errors": errors}


def import_legacy_storage(user_id: int) -> dict:
    """Import only configured legacy roots; no request path is ever accepted."""
    ensure_root_folders(user_id)
    roots = _root_assets(user_id)
    imported = 0
    skipped = 0
    errors: list[dict] = []
    for legacy_name in config.INDEXED_DIRECTORIES:
        source_root = config.DATA_ROOT / legacy_name
        parent_map: dict[Path, str] = {source_root: roots[legacy_name]}
        for source in sorted(source_root.rglob("*"), key=lambda p: (len(p.parts), str(p).lower())):
            asset_id = None
            destination = None
            try:
                parent_id = parent_map[source.parent]
                if source.is_dir():
                    folder = _find_or_create_folder(user_id, parent_id, source.name)
                    parent_map[source] = folder.id
                    continue
                mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
                digest = sha256_file(source)
                asset_id = str(uuid4())
                destination = allocate_storage_path(user_id, asset_id)
                shutil.copy2(source, destination)
                asset = create_file_asset(
                    user_id, asset_id, source.name, destination, destination.stat().st_size,
                    digest, mime, parent_id,
                )
                if asset.type == "image":
                    try:
                        generate_thumbnail(asset.id, user_id, destination)
                    except Exception:
                        # Thumbnail and EXIF extraction are best-effort scanner work.
                        pass
                imported += 1
            except Exception as exc:
                if asset_id:
                    with connection() as conn:
                        conn.execute("DELETE FROM assets WHERE id=? AND user_id=?", (asset_id, user_id))
                if destination:
                    destination.unlink(missing_ok=True)
                errors.append({"name": source.name, "error": str(exc)})
    return {"imported": imported, "skipped_duplicates": skipped, "errors": errors}


def _root_assets(user_id: int) -> dict[str, str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id,filename FROM assets WHERE user_id=? AND parent_id IS NULL AND is_deleted=0", (user_id,)
        ).fetchall()
    return {row["filename"]: row["id"] for row in rows}


def _find_or_create_folder(user_id: int, parent_id: str, filename: str):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND parent_id=? AND filename=? AND type='folder' AND is_deleted=0",
            (user_id, parent_id, filename),
        ).fetchone()
    if row:
        from backend.models.asset import Asset
        return Asset.from_row(row)
    return create_folder(user_id, filename, parent_id)


def _find_or_create_root_folder(user_id: int, filename: str):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND parent_id IS NULL AND filename=? "
            "AND type='folder' AND is_deleted=0",
            (user_id, filename),
        ).fetchone()
    if row:
        from backend.models.asset import Asset
        return Asset.from_row(row)
    return create_folder(user_id, filename, None)


# ---------------------------------------------------------------------------
# Disk Scanner public API — progress tracking, status, scheduler
# ---------------------------------------------------------------------------

_log = logging.getLogger("mynas.scan")


def is_scan_running() -> bool:
    """Check if a scan is currently in progress."""
    with _scan_lock:
        return bool(_running_scans)


def get_scan_status(user_id: int) -> dict:
    """Read persisted scan status from settings table (restart-safe)."""
    raw = get_setting(f"scan_status_{user_id}")
    if raw:
        status = json.loads(raw)
        # Server restarted mid-scan → no scan is actually running
        if status.get("state") == "running" and not is_scan_running():
            status["state"] = "interrupted"
        return status
    return {
        "state": "idle", "scanned": 0, "imported": 0, "skipped": 0,
        "errors": 0, "started_at": None, "finished_at": None, "elapsed": None,
    }


def _persist_status(user_id: int, status: dict):
    set_setting(f"scan_status_{user_id}", json.dumps(status))


def run_disk_scan(user_id: int) -> dict:
    """Full scan: legacy directories + all registered storage locations.

    Thread-safe via existing ``_scan_lock`` / ``_running_scans`` guard.
    Status is persisted to the settings table so ``get_scan_status`` is
    restart-safe.  Uses the existing ``import_legacy_storage`` for
    INDEXED_DIRECTORIES and ``_scan_registered_storage`` for each
    storage location — no new scan logic.
    """
    with _scan_lock:
        if user_id in _running_scans:
            _log.info("scan: already running for user %s, skipping", user_id)
            return get_scan_status(user_id)
        _running_scans.add(user_id)

    started_at = utc_now()
    _persist_status(user_id, {
        "state": "running", "scanned": 0, "imported": 0, "skipped": 0,
        "errors": 0, "started_at": started_at, "finished_at": None, "elapsed": None,
    })
    t0 = time.monotonic()
    total_imported = 0
    total_skipped = 0
    total_errors: list[dict] = []
    try:
        # Phase 1: legacy INDEXED_DIRECTORIES
        legacy = import_legacy_storage(user_id)
        total_imported += legacy["imported"]
        total_skipped += legacy["skipped_duplicates"]
        total_errors.extend(legacy["errors"])

        # Phase 2: each registered storage location
        with connection() as conn:
            locations = conn.execute(
                "SELECT id FROM storage_locations WHERE user_id=?", (user_id,)
            ).fetchall()
        for loc in locations:
            try:
                result = _scan_registered_storage(user_id, loc["id"])
                total_imported += result["imported"]
                total_skipped += result["skipped_existing"]
                total_errors.extend(result["errors"])
            except Exception as exc:
                total_errors.append({"name": loc["id"], "error": str(exc)})

        elapsed = round(time.monotonic() - t0, 2)
        scanned = total_imported + total_skipped
        status = {
            "state": "completed",
            "scanned": scanned,
            "imported": total_imported,
            "skipped": total_skipped,
            "errors": len(total_errors),
            "started_at": started_at,
            "finished_at": utc_now(),
            "elapsed": elapsed,
        }
        _persist_status(user_id, status)
        audit("scan", "system", user_id,
              detail=f"imported={total_imported} skipped={total_skipped} "
                     f"errors={len(total_errors)} elapsed={elapsed}s")
        _log.info("scan complete: %s", status)
        return status
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        status = {
            "state": "failed", "scanned": 0, "imported": 0, "skipped": 0,
            "errors": 1, "started_at": started_at,
            "finished_at": utc_now(), "elapsed": elapsed,
        }
        _persist_status(user_id, status)
        _log.exception("scan failed: %s", exc)
        return status
    finally:
        with _scan_lock:
            _running_scans.discard(user_id)


def start_scan_scheduler(user_id: int):
    """Register a 10-minute interval scan on the existing APScheduler."""
    from backend.services.backup_service import scheduler
    job_id = f"scan_{user_id}"
    if scheduler.get_job(job_id):
        return
    scheduler.add_job(
        run_disk_scan, "interval", minutes=10,
        args=[user_id], id=job_id, replace_existing=True,
        max_instances=1, misfire_grace_time=60,
    )
    _log.info("scan: scheduled every 10 minutes for user %s", user_id)


def stop_scan_scheduler(user_id: int):
    """Remove the periodic scan job."""
    from backend.services.backup_service import scheduler
    job_id = f"scan_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
