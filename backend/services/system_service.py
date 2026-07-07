import socket
import shutil

from backend import config
from backend.db.database import connection, recent_audit_logs
from backend.models.asset import Asset
from backend.services.asset_service import dashboard_categories, public_asset
from backend.services.backup_service import backup_logs
from backend.utils.files import size_label


def dashboard(user_id: int) -> dict:
    disk = shutil.disk_usage(config.DATA_ROOT)
    with connection() as conn:
        counts = conn.execute(
            "SELECT COUNT(*) asset_count, SUM(type='image') photo_count, SUM(type='video') video_count, "
            "SUM(type='file') file_count, SUM(is_favorite=1) favorite_count "
            "FROM assets WHERE user_id=? AND is_deleted=0", (user_id,),
        ).fetchone()
        recent_rows = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND type='image' AND is_deleted=0 ORDER BY created_at DESC LIMIT 6",
            (user_id,),
        ).fetchall()
    latest_backup = backup_logs(user_id, 1)
    return {
        "device_name": _device_name(),
        "data_root": "MyNAS Secure Storage",
        "disk": {
            "total": disk.total, "used": disk.used, "free": disk.free,
            "percent": round(disk.used / disk.total * 100, 1),
            "total_label": size_label(disk.total), "used_label": size_label(disk.used),
            "free_label": size_label(disk.free),
        },
        "categories": dashboard_categories(user_id),
        "stats": {
            "asset_count": counts["asset_count"] or 0,
            "photo_count": counts["photo_count"] or 0,
            "video_count": counts["video_count"] or 0,
            "file_count": counts["file_count"] or 0,
            "favorite_count": counts["favorite_count"] or 0,
        },
        "recent_photos": [public_asset(Asset.from_row(row)) for row in recent_rows],
        "backup": latest_backup[0] if latest_backup else {"status": "never", "finished_at": None},
        "health": {"status": "healthy", "database": "online", "storage": "online"},
        "activities": [
            {"id": row["id"], "action": row["action"], "target": row["asset_id"] or "", "detail": row["detail"], "created_at": row["created_at"]}
            for row in recent_audit_logs(user_id, 8)
        ],
    }


def _device_name() -> str:
    try:
        return socket.gethostname().strip() or "MyNAS Node"
    except OSError:
        return "MyNAS Node"
