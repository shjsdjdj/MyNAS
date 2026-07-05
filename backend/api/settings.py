from uuid import UUID

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import active_user
from backend.core.security import client_ip
from backend.db.database import audit
from backend.models.settings import (
    BackupSettingsUpdate, PreferencesUpdate, StorageLocationCreate,
    StorageLocationUpdate, UsernameRequest,
)
from backend.services.auth_service import change_username
from backend.services.backup_service import run_incremental_backup
from backend.services.scan_service import start_background_scan
from backend.services.settings_service import (
    backup_settings, create_storage_location, delete_storage_location,
    get_preferences, list_storage_locations, set_default_storage,
    system_information, update_backup_settings, update_preferences,
    update_storage_location,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.patch("/account/username")
def username(payload: UsernameRequest, request: Request, user: dict = Depends(active_user)):
    updated = change_username(user["id"], payload.username)
    audit("username_change", client_ip(request), user["id"], detail=payload.username)
    return updated


@router.get("/preferences")
def preferences(user: dict = Depends(active_user)):
    return get_preferences(user["id"])


@router.patch("/preferences")
def save_preferences(payload: PreferencesUpdate, request: Request, user: dict = Depends(active_user)):
    result = update_preferences(user["id"], payload.model_dump())
    audit("preferences_update", client_ip(request), user["id"])
    return result


@router.get("/storage")
def storage_locations(user: dict = Depends(active_user)):
    return {"items": list_storage_locations(user["id"])}


@router.post("/storage")
def add_storage(payload: StorageLocationCreate, request: Request, user: dict = Depends(active_user)):
    result = create_storage_location(user["id"], payload.name, payload.path, payload.is_default)
    audit("storage_create", client_ip(request), user["id"], detail=result["name"])
    return {**result, **start_background_scan(user["id"], result["id"])}


@router.patch("/storage/{location_id}")
def edit_storage(location_id: UUID, payload: StorageLocationUpdate, request: Request, user: dict = Depends(active_user)):
    result = update_storage_location(user["id"], str(location_id), payload.name, payload.path)
    audit("storage_update", client_ip(request), user["id"], detail=result["name"])
    return result


@router.delete("/storage/{location_id}")
def remove_storage(location_id: UUID, request: Request, user: dict = Depends(active_user)):
    delete_storage_location(user["id"], str(location_id))
    audit("storage_delete", client_ip(request), user["id"], detail=str(location_id))
    return {"deleted": str(location_id)}


@router.post("/storage/{location_id}/default")
def make_default_storage(location_id: UUID, request: Request, user: dict = Depends(active_user)):
    result = set_default_storage(user["id"], str(location_id))
    audit("storage_default", client_ip(request), user["id"], detail=result["name"])
    return result


@router.get("/backup")
def get_backup_settings(user: dict = Depends(active_user)):
    return backup_settings(user["id"])


@router.patch("/backup")
def save_backup_settings(payload: BackupSettingsUpdate, request: Request, user: dict = Depends(active_user)):
    result = update_backup_settings(user["id"], payload.directory, payload.enabled, payload.daily_time)
    audit("backup_settings_update", client_ip(request), user["id"])
    return result


@router.post("/backup/run")
def run_backup_now(request: Request, user: dict = Depends(active_user)):
    return run_incremental_backup(user["id"], client_ip(request))


@router.get("/system")
def system(user: dict = Depends(active_user)):
    return system_information(user["id"])
