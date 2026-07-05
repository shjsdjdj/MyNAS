from uuid import UUID

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import active_user
from backend.core.security import client_ip
from backend.db.database import audit
from backend.services.asset_service import (
    empty_trash, list_trash, permanent_delete_asset, restore_asset
)

router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("")
def get_trash(user: dict = Depends(active_user)):
    items = list_trash(user["id"])
    return {"items": items}


@router.post("/{asset_id}/restore")
def restore(asset_id: UUID, request: Request, user: dict = Depends(active_user)):
    asset = restore_asset(user["id"], str(asset_id))
    audit("restore", client_ip(request), user["id"], asset.id, asset.filename)
    return {"restored": asset.id}


@router.delete("/{asset_id}/permanent")
def permanent_delete(asset_id: UUID, request: Request, user: dict = Depends(active_user)):
    asset = permanent_delete_asset(user["id"], str(asset_id))
    audit("permanent_delete", client_ip(request), user["id"], asset.id, asset.filename)
    return {"deleted": asset.id}


@router.delete("")
def empty_trash_endpoint(request: Request, user: dict = Depends(active_user)):
    deleted_ids = empty_trash(user["id"])
    audit("empty_trash", client_ip(request), user["id"], detail=f"Deleted {len(deleted_ids)} items")
    return {"deleted_ids": deleted_ids}
