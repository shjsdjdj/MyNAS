from pydantic import BaseModel, Field


class UsernameRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


class StorageLocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=3, max_length=260)
    is_default: bool = False


class StorageLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    path: str | None = Field(default=None, min_length=3, max_length=260)


class PreferencesUpdate(BaseModel):
    language: str | None = None
    theme: str | None = None
    default_home: str | None = None
    default_upload_directory: str | None = None
    photo_sort: str | None = None


class BackupSettingsUpdate(BaseModel):
    directory: str | None = Field(default=None, min_length=3, max_length=260)
    enabled: bool | None = None
    daily_time: str | None = None
