import os
import shutil
from pathlib import Path
from uuid import uuid4

from anyio import to_thread
from fastapi import BackgroundTasks, UploadFile

from backend import config
from backend.core.security import safe_display_filename, validate_upload
from backend.db.database import connection
from backend.services.asset_service import (
    create_file_asset, create_folder, delete_asset, find_duplicate, get_owned_asset, public_asset,
)
from backend.services.thumbnail_service import generate_thumbnail
from backend.storage.secure_storage import allocate_storage_path, validate_internal_path
from backend.utils.files import sha256_file


async def secure_upload(user_id: int, parent_id: str, incoming: UploadFile, background_tasks: BackgroundTasks | None = None) -> dict:
    parent = get_owned_asset(parent_id, user_id)
    if parent.type != "folder":
        raise ValueError("上传目标不是文件夹")
    display_name = safe_display_filename(incoming.filename)
    asset_id = str(uuid4())
    destination = allocate_storage_path(user_id, asset_id)
    asset_created = False
    try:
        # Validate header BEFORE writing anything to disk
        header = await incoming.read(32)
        if not header:
            raise ValueError("文件为空")
        validate_upload(display_name, incoming.content_type, header)
        total = len(header)
        with destination.open("xb") as output:
            await to_thread.run_sync(output.write, header)
            while chunk := await incoming.read(1024 * 1024):
                total += len(chunk)
                if total > config.MAX_UPLOAD_BYTES:
                    raise ValueError("文件超过允许的大小")
                await to_thread.run_sync(output.write, chunk)
        digest = sha256_file(destination)
        duplicate = find_duplicate(user_id, digest)
        if duplicate:
            # Keep one Asset per uploaded file while deduplicating bytes when the
            # filesystem supports hard links. Every Asset still owns a distinct
            # UUID path, so authorization and lifecycle operations stay isolated.
            duplicate_path = validate_internal_path(user_id, duplicate.storage_path)
            destination.unlink(missing_ok=True)
            try:
                os.link(duplicate_path, destination)
            except OSError:
                shutil.copy2(duplicate_path, destination)
        asset = create_file_asset(
            user_id, asset_id, display_name, destination, total, digest,
            (incoming.content_type or "application/octet-stream").split(";", 1)[0], parent_id,
        )
        asset_created = True
        if asset.type == "image":
            if not generate_thumbnail(asset.id, user_id, destination):
                raise ValueError("图片内容损坏，无法生成缩略图")
            asset = get_owned_asset(asset.id, user_id)
        return {"asset": public_asset(asset), "duplicate": duplicate is not None}
    except Exception:
        if asset_created:
            with connection() as conn:
                conn.execute("DELETE FROM assets WHERE id=? AND user_id=?", (asset_id, user_id))
        thumbnail = config.DATA_ROOT / "Thumbnails" / str(user_id) / f"{asset_id}.jpg"
        thumbnail.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def secure_download(user_id: int, asset_id: str) -> tuple[Path, object]:
    asset = get_owned_asset(asset_id, user_id)
    if asset.type == "folder":
        raise ValueError("文件夹不可下载")
    path = validate_internal_path(user_id, asset.storage_path)
    if not path.is_file():
        raise FileNotFoundError("磁盘文件不存在")
    return path, asset


def secure_delete(user_id: int, asset_id: str):
    return delete_asset(user_id, asset_id)


def secure_create_folder(user_id: int, name: str, parent_id: str | None):
    display_name = safe_display_filename(name)
    return create_folder(user_id, display_name, parent_id)
