from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import active_user, admin_user
from backend.services.scan_service import (
    get_scan_status, is_scan_running, run_disk_scan, start_scan_scheduler,
    stop_scan_scheduler,
)

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.post("")
def trigger_scan(user: dict = Depends(admin_user)):
    """Trigger a background disk scan.  Admin only."""
    if is_scan_running():
        raise HTTPException(409, "扫描正在进行中")
    from backend.services.backup_service import scheduler
    scheduler.add_job(
        run_disk_scan, args=[user["id"]],
        id=f"scan_manual_{user['id']}", replace_existing=True,
        max_instances=1,
    )
    return {"status": "started"}


@router.get("/status")
def scan_status(user: dict = Depends(active_user)):
    """Return current / last scan result."""
    return get_scan_status(user["id"])
