from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from backend.api.dependencies import active_user
from backend.core.security import client_ip
from backend.db.database import audit
from backend.models.asset import FavoriteRequest, FolderCreateRequest, TagsRequest
from backend.services.asset_service import list_assets, public_asset, set_favorite, set_tags
from backend.services.file_service import secure_create_folder, secure_delete, secure_download, secure_upload

router = APIRouter(prefix="/api", tags=["assets"])


@router.get("/assets")
@router.get("/assets/list", include_in_schema=False)
def assets_list(parent_id: UUID | None = None, user: dict = Depends(active_user)):
    return list_assets(user["id"], str(parent_id) if parent_id else None)


@router.post("/upload")
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    parent_id: UUID = Form(...),
    files: list[UploadFile] = File(...),
    user: dict = Depends(active_user),
):
    assets, uploaded, duplicates = [], [], []
    for incoming in files:
        result = await secure_upload(user["id"], str(parent_id), incoming, background_tasks)
        asset = result["asset"]
        assets.append(asset)
        audit("upload_duplicate" if result["duplicate"] else "upload", client_ip(request), user["id"], asset["id"], asset["filename"])
        (duplicates if result["duplicate"] else uploaded).append(asset)
    return {
        "assets": assets,
        "uploaded": uploaded,
        "duplicates": duplicates,
        "count": len(assets),
    }


@router.post("/assets/folder")
def new_folder(payload: FolderCreateRequest, request: Request, user: dict = Depends(active_user)):
    asset = secure_create_folder(user["id"], payload.name, payload.parent_id)
    public = public_asset(asset)
    audit("create_folder", client_ip(request), user["id"], asset.id, asset.filename)
    return public


@router.get("/assets/{asset_id}")
@router.get("/asset/{asset_id}", include_in_schema=False)
def download_asset(asset_id: UUID, request: Request, user: dict = Depends(active_user)):
    path, asset = secure_download(user["id"], str(asset_id))
    audit("download", client_ip(request), user["id"], asset.id, asset.filename)
    return FileResponse(path, filename=asset.filename, media_type=asset.mime_type)


@router.delete("/assets/{asset_id}")
@router.delete("/asset/{asset_id}", include_in_schema=False)
def remove_asset(asset_id: UUID, request: Request, user: dict = Depends(active_user)):
    asset = secure_delete(user["id"], str(asset_id))
    audit("delete", client_ip(request), user["id"], asset.id, asset.filename)
    return {"deleted": asset.id}


@router.patch("/assets/{asset_id}/tags")
@router.patch("/asset/{asset_id}/tags", include_in_schema=False)
def update_tags(asset_id: UUID, payload: TagsRequest, request: Request, user: dict = Depends(active_user)):
    asset = set_tags(user["id"], str(asset_id), payload.tags)
    audit("tags_update", client_ip(request), user["id"], asset.id)
    return public_asset(asset)


@router.patch("/assets/{asset_id}/favorite")
def update_favorite(asset_id: UUID, payload: FavoriteRequest, request: Request, user: dict = Depends(active_user)):
    asset = set_favorite(user["id"], str(asset_id), payload.is_favorite)
    audit("favorite", client_ip(request), user["id"], asset.id, detail=str(asset.is_favorite))
    return public_asset(asset)
