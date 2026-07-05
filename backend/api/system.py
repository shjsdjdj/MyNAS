from fastapi import APIRouter, Depends, Query, Request

from backend.api.dependencies import active_user, admin_user
from backend.core.security import client_ip
from backend.db.database import all_audit_logs, audit, recent_audit_logs
from backend.services.scan_service import import_legacy_storage
from backend.services.system_service import dashboard

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(user: dict = Depends(active_user)):
    return {"status": "online", "mode": "secure", "user_id": user["id"]}


@router.get("/dashboard")
def get_dashboard(user: dict = Depends(active_user)):
    return dashboard(user["id"])


@router.post("/assets/import-legacy")
def import_legacy(request: Request, user: dict = Depends(admin_user)):
    result = import_legacy_storage(user["id"])
    audit("legacy_import", client_ip(request), user["id"], detail=str(result))
    return result


@router.get("/audit-logs")
def audit_logs(limit: int = Query(50, ge=1, le=500), user: dict = Depends(active_user)):
    return {"items": recent_audit_logs(user["id"], limit)}


@router.get("/admin/audit-logs")
def admin_audit_logs(limit: int = Query(50, ge=1, le=500), user: dict = Depends(admin_user)):
    return {"items": all_audit_logs(limit)}
