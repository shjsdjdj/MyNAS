from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import active_user
from backend.core.security import client_ip
from backend.db.database import audit
from backend.models.backup import BackupScheduleRequest
from backend.services.backup_service import backup_logs, configure_schedule, run_incremental_backup

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.post("/run")
def run_backup(request: Request, user: dict = Depends(active_user)):
    return run_incremental_backup(user["id"], client_ip(request))


@router.get("/logs")
def logs(user: dict = Depends(active_user)):
    return {"items": backup_logs(user["id"])}


@router.post("/schedule")
def schedule(payload: BackupScheduleRequest, request: Request, user: dict = Depends(active_user)):
    result = configure_schedule(user["id"], payload.interval_minutes, payload.enabled)
    audit("backup_schedule", client_ip(request), user["id"], detail=f"enabled={payload.enabled}; interval={payload.interval_minutes}")
    return result
