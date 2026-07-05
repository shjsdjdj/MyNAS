import json
from typing import Literal

from pydantic import BaseModel, Field


class Asset(BaseModel):
    id: str
    user_id: int
    filename: str
    storage_path: str
    type: Literal["file", "image", "video", "folder"]
    size: int
    hash: str | None = None
    created_at: str
    updated_at: str
    mime_type: str
    is_deleted: bool = False
    deleted_at: str | None = None
    parent_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    thumbnail_storage_path: str | None = None
    exif_datetime: str | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_url: str | None = None
    is_favorite: bool = False

    @classmethod
    def from_row(cls, row):
        data = dict(row)
        data["tags"] = json.loads(data.get("tags") or "[]")
        data["is_deleted"] = bool(data.get("is_deleted"))
        data["is_favorite"] = bool(data.get("is_favorite"))
        return cls(**data)


class AssetPublic(BaseModel):
    id: str
    filename: str
    type: str
    size: int
    hash: str | None
    created_at: str
    updated_at: str
    mime_type: str
    parent_id: str | None
    tags: list[str]
    thumbnail_url: str | None
    is_directory: bool
    size_label: str
    deleted_at: str | None = None
    exif_datetime: str | None = None
    width: int | None = None
    height: int | None = None
    is_favorite: bool = False


class FolderCreateRequest(BaseModel):
    name: str
    parent_id: str | None = None


class TagsRequest(BaseModel):
    tags: list[str]


class FavoriteRequest(BaseModel):
    is_favorite: bool | None = None
