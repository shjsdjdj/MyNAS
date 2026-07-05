from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend import config
from backend.api.dependencies import active_user
from backend.core.security import client_ip
from backend.db.database import audit
from backend.models.asset import FavoriteRequest
from backend.services.asset_service import get_owned_asset, public_asset, set_favorite
from backend.services.photo_service import photos_page, search, timeline_page

router = APIRouter(prefix="/api/photos", tags=["photos"])
asset_router = APIRouter(prefix="/api/asset", tags=["photos"])
assets_router = APIRouter(prefix="/api/assets", tags=["photos"])


@router.get("")
def photos(
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    user: dict = Depends(active_user),
):
    return photos_page(user["id"], page, page_size)


@router.get("/timeline")
def photo_timeline(
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=100),
    period: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: dict = Depends(active_user),
):
    return timeline_page(user["id"], page, page_size, period, date_from, date_to)


@router.get("/recent")
def recent_photos(
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    user: dict = Depends(active_user),
):
    return photos_page(user["id"], page, page_size, recent=True)


@router.get("/favorites")
def favorite_photos(
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    user: dict = Depends(active_user),
):
    return photos_page(user["id"], page, page_size, favorite_only=True)


@router.get("/search")
def photo_search(
    q: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    user: dict = Depends(active_user),
):
    return search(user["id"], q, date_from, date_to, page, page_size)


@router.get("/{asset_id}/thumbnail", include_in_schema=False)
@asset_router.get("/{asset_id}/thumbnail")
@assets_router.get("/{asset_id}/thumbnail")
def thumbnail(asset_id: UUID, request: Request, user: dict = Depends(active_user)):
    asset = get_owned_asset(str(asset_id), user["id"])
    if asset.type != "image" or not asset.thumbnail_storage_path:
        raise HTTPException(404, "缩略图不存在")
    path = Path(asset.thumbnail_storage_path).resolve()
    expected_root = (config.DATA_ROOT / "Thumbnails" / str(user["id"])).resolve()
    if expected_root not in path.parents or not path.is_file():
        raise HTTPException(404, "缩略图不存在")
    audit("thumbnail", client_ip(request), user["id"], asset.id)
    return FileResponse(path, media_type="image/jpeg")


@asset_router.patch("/{asset_id}/favorite")
def favorite(asset_id: UUID, payload: FavoriteRequest, request: Request, user: dict = Depends(active_user)):
    asset = set_favorite(user["id"], str(asset_id), payload.is_favorite)
    audit("favorite", client_ip(request), user["id"], asset.id, detail=str(asset.is_favorite))
    return public_asset(asset)
