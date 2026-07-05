from pathlib import Path
from uuid import UUID

from backend import config


def user_storage_root(user_id: int) -> Path:
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("无效用户")
    root = (config.DATA_ROOT / "Storage" / str(user_id)).resolve()
    storage_root = (config.DATA_ROOT / "Storage").resolve()
    if storage_root not in root.parents:
        raise ValueError("存储路径越界")
    root.mkdir(parents=True, exist_ok=True)
    return root


def allocate_storage_path(user_id: int, asset_id: str) -> Path:
    canonical_id = str(UUID(asset_id))
    root = user_storage_root(user_id)
    target = (root / canonical_id).resolve()
    if root not in target.parents:
        raise ValueError("存储路径越界")
    return target


def validate_internal_path(user_id: int, path: str) -> Path:
    root = user_storage_root(user_id)
    target = Path(path).resolve()
    if root not in target.parents:
        raise ValueError("资产存储路径无效")
    return target
