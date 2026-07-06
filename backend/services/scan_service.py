import mimetypes
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from backend import config
from backend.db.database import connection
from backend.services.asset_service import (
    create_file_asset, create_folder, ensure_root_folders, get_owned_asset,
)
from backend.services.thumbnail_service import generate_thumbnail, remove_thumbnail
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
    return _scan_source_tree(
        user_id=user_id,
        source_root=source_root,
        root_asset_id=root_asset.id,
        namespace=UUID(location_id),
        legacy=False,
    )


def import_legacy_storage(user_id: int) -> dict:
    """Import only configured legacy roots; no request path is ever accepted."""
    ensure_root_folders(user_id)
    roots = _root_assets(user_id)
    imported = 0
    updated = 0
    deleted = 0
    skipped = 0
    errors: list[dict] = []
    for legacy_name in config.INDEXED_DIRECTORIES:
        source_root = config.DATA_ROOT / legacy_name
        namespace = uuid5(NAMESPACE_URL, f"mynas:legacy:{user_id}:{legacy_name.lower()}")
        result = _scan_source_tree(
            user_id=user_id,
            source_root=source_root,
            root_asset_id=roots[legacy_name],
            namespace=namespace,
            legacy=True,
        )
        imported += result["imported"]
        updated += result["updated"]
        deleted += result["deleted"]
        skipped += result["skipped_existing"]
        errors.extend(result["errors"])
    return {
        "imported": imported,
        "updated": updated,
        "deleted": deleted,
        "skipped_duplicates": skipped,
        "errors": errors,
    }


def _scan_source_tree(
    *, user_id: int, source_root: Path, root_asset_id: str,
    namespace: UUID, legacy: bool,
) -> dict:
    """Reconcile one trusted source tree without applying upload validation."""
    sources = _retry_io(
        lambda: sorted(source_root.rglob("*"), key=lambda p: (len(p.parts), str(p).lower()))
    )
    parent_map: dict[Path, str] = {source_root: root_asset_id}
    seen_ids: set[str] = set()
    imported = updated = skipped = 0
    errors: list[dict] = []

    for source in sources:
        relative_path = source.relative_to(source_root).as_posix()
        deterministic_id = str(uuid5(namespace, relative_path.lower()))
        try:
            parent_id = parent_map[source.parent]
            if source.is_dir():
                folder = _find_or_create_folder(user_id, parent_id, source.name)
                parent_map[source] = folder.id
                continue

            # Mark the deterministic identity as observed before file IO. If a
            # currently indexed file is temporarily locked, reconciliation must
            # not misclassify it as deleted.
            seen_ids.add(deterministic_id)
            status, canonical_id = _reconcile_file(
                user_id=user_id,
                source=source,
                parent_id=parent_id,
                asset_id=deterministic_id,
                legacy=legacy,
            )
            seen_ids.add(canonical_id)
            if status == "imported":
                imported += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"name": source.name, "error": str(exc)})

    # ``sources`` was materialized successfully before any writes. It is safe
    # to reconcile missing deterministic scanner assets. A missing/unavailable
    # root raises above and therefore never reaches this operation.
    deleted = _soft_delete_missing(user_id, root_asset_id, namespace, seen_ids)
    return {
        "imported": imported,
        "updated": updated,
        "deleted": deleted,
        "skipped_existing": skipped,
        "errors": errors,
    }


def _reconcile_file(
    *, user_id: int, source: Path, parent_id: str,
    asset_id: str, legacy: bool,
) -> tuple[str, str]:
    digest = _retry_io(lambda: sha256_file(source))
    mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "file"

    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM assets WHERE id=? AND user_id=?", (asset_id, user_id)
        ).fetchone()
        candidates = []
        if legacy:
            candidates = conn.execute(
                "SELECT * FROM assets WHERE user_id=? AND parent_id=? AND filename=? AND type!='folder' "
                "ORDER BY is_deleted,created_at,id",
                (user_id, parent_id, source.name),
            ).fetchall()
            if not existing and candidates:
                # Only adopt a pre-v3.2 legacy row when its bytes match. A
                # same-name upload in the shared logical folder must never be
                # mistaken for scanner-owned data.
                matching = next((row for row in candidates if row["hash"] == digest), None)
            else:
                matching = None
            if matching is not None:
                old_id = matching["id"]
                conn.execute("UPDATE assets SET id=? WHERE id=? AND user_id=?", (asset_id, old_id, user_id))
                conn.execute(
                    "UPDATE backup_entries SET source_asset_id=? WHERE source_asset_id=? AND user_id=?",
                    (asset_id, old_id, user_id),
                )
                conn.execute(
                    "UPDATE audit_logs SET asset_id=? WHERE asset_id=? AND user_id=?",
                    (asset_id, old_id, user_id),
                )
                existing = conn.execute(
                    "SELECT * FROM assets WHERE id=? AND user_id=?", (asset_id, user_id)
                ).fetchone()

    if existing and existing["hash"] == digest and Path(existing["storage_path"]).is_file():
        now = _source_modified_at(source)
        with connection() as conn:
            conn.execute(
                "UPDATE assets SET filename=?,parent_id=?,type=?,size=?,mime_type=?,updated_at=?,"
                "is_deleted=0,deleted_at=NULL WHERE id=? AND user_id=?",
                (
                    source.name, parent_id, kind, source.stat().st_size, mime, now,
                    asset_id, user_id,
                ),
            )
            if legacy:
                conn.execute(
                    "UPDATE assets SET is_deleted=1,deleted_at=?,updated_at=? "
                    "WHERE user_id=? AND parent_id=? AND filename=? AND id!=? AND hash=? AND type!='folder'",
                    (utc_now(), utc_now(), user_id, parent_id, source.name, asset_id, digest),
                )
        if kind == "image" and not existing["thumbnail_storage_path"]:
            try:
                generate_thumbnail(asset_id, user_id, Path(existing["storage_path"]))
            except Exception:
                pass
        return "skipped", asset_id

    destination = Path(existing["storage_path"]) if existing else allocate_storage_path(user_id, asset_id)
    staged = destination.parent / f".{destination.name}.{uuid4().hex}.scan-tmp"
    rollback = destination.parent / f".{destination.name}.{uuid4().hex}.scan-old"
    old_thumbnail = existing["thumbnail_storage_path"] if existing else None
    try:
        _retry_io(lambda: shutil.copy2(source, staged))
        if _retry_io(lambda: sha256_file(staged)) != digest:
            raise OSError("Copied file failed SHA256 verification")
        had_destination = destination.is_file()
        if had_destination:
            os.replace(destination, rollback)
        os.replace(staged, destination)
        try:
            if existing:
                with connection() as conn:
                    conn.execute(
                        "UPDATE assets SET filename=?,storage_path=?,type=?,size=?,hash=?,updated_at=?,mime_type=?,"
                        "parent_id=?,is_deleted=0,deleted_at=NULL,thumbnail_storage_path=NULL,thumbnail_url=NULL,"
                        "exif_datetime=NULL,width=NULL,height=NULL WHERE id=? AND user_id=?",
                        (
                            source.name, str(destination), kind, destination.stat().st_size, digest,
                            _source_modified_at(source), mime, parent_id, asset_id, user_id,
                        ),
                    )
                status = "updated"
            else:
                create_file_asset(
                    user_id, asset_id, source.name, destination, destination.stat().st_size,
                    digest, mime, parent_id,
                )
                status = "imported"
        except Exception:
            destination.unlink(missing_ok=True)
            if rollback.exists():
                os.replace(rollback, destination)
            raise
        rollback.unlink(missing_ok=True)
    finally:
        staged.unlink(missing_ok=True)

    remove_thumbnail(old_thumbnail, user_id)
    if kind == "image":
        try:
            generate_thumbnail(asset_id, user_id, destination)
        except Exception:
            pass
    if legacy:
        with connection() as conn:
            conn.execute(
                "UPDATE assets SET is_deleted=1,deleted_at=?,updated_at=? "
                "WHERE user_id=? AND parent_id=? AND filename=? AND id!=? AND hash=? AND type!='folder'",
                (utc_now(), utc_now(), user_id, parent_id, source.name, asset_id, digest),
            )
    return status, asset_id


def _soft_delete_missing(user_id: int, root_asset_id: str, namespace: UUID, seen_ids: set[str]) -> int:
    with connection() as conn:
        rows = conn.execute(
            "WITH RECURSIVE tree(id,parent_id,filename,type,relative_path) AS ("
            "SELECT id,parent_id,filename,type,'' FROM assets WHERE id=? AND user_id=? "
            "UNION ALL SELECT a.id,a.parent_id,a.filename,a.type,"
            "CASE WHEN t.relative_path='' THEN a.filename ELSE t.relative_path||'/'||a.filename END "
            "FROM assets a JOIN tree t ON a.parent_id=t.id WHERE a.user_id=?) "
            "SELECT id,type,relative_path FROM tree WHERE type!='folder' "
            "AND id IN (SELECT id FROM assets WHERE user_id=? AND is_deleted=0)",
            (root_asset_id, user_id, user_id, user_id),
        ).fetchall()
        missing = [
            row["id"] for row in rows
            if row["id"] == str(uuid5(namespace, row["relative_path"].lower()))
            and row["id"] not in seen_ids
        ]
        if missing:
            now = utc_now()
            conn.executemany(
                "UPDATE assets SET is_deleted=1,deleted_at=?,updated_at=? "
                "WHERE id=? AND user_id=? AND is_deleted=0",
                [(now, now, asset_id, user_id) for asset_id in missing],
            )
    return len(missing)


def _retry_io(operation, attempts: int = 3):
    last_error = None
    for attempt in range(attempts):
        try:
            return operation()
        except OSError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.05 * (2 ** attempt))
    raise last_error


def _source_modified_at(source: Path) -> str:
    return datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()


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
        "state": "idle", "scanned": 0, "imported": 0, "updated": 0,
        "deleted": 0, "skipped": 0,
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
        "state": "running", "scanned": 0, "imported": 0, "updated": 0,
        "deleted": 0, "skipped": 0,
        "errors": 0, "started_at": started_at, "finished_at": None, "elapsed": None,
    })
    t0 = time.monotonic()
    total_imported = 0
    total_updated = 0
    total_deleted = 0
    total_skipped = 0
    total_errors: list[dict] = []
    try:
        # Phase 1: legacy INDEXED_DIRECTORIES
        legacy = import_legacy_storage(user_id)
        total_imported += legacy["imported"]
        total_updated += legacy["updated"]
        total_deleted += legacy["deleted"]
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
                total_updated += result["updated"]
                total_deleted += result["deleted"]
                total_skipped += result["skipped_existing"]
                total_errors.extend(result["errors"])
            except Exception as exc:
                total_errors.append({"name": loc["id"], "error": str(exc)})

        elapsed = round(time.monotonic() - t0, 2)
        scanned = total_imported + total_updated + total_skipped
        status = {
            "state": "completed",
            "scanned": scanned,
            "imported": total_imported,
            "updated": total_updated,
            "deleted": total_deleted,
            "skipped": total_skipped,
            "errors": len(total_errors),
            "started_at": started_at,
            "finished_at": utc_now(),
            "elapsed": elapsed,
        }
        _persist_status(user_id, status)
        audit("scan", "system", user_id,
              detail=f"imported={total_imported} updated={total_updated} deleted={total_deleted} "
                     f"skipped={total_skipped} "
                     f"errors={len(total_errors)} elapsed={elapsed}s")
        _log.info("scan complete: %s", status)
        return status
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 2)
        status = {
            "state": "failed", "scanned": 0, "imported": 0, "updated": 0,
            "deleted": 0, "skipped": 0,
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
