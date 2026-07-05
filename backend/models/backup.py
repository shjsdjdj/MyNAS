from pydantic import BaseModel, Field


class BackupScheduleRequest(BaseModel):
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    enabled: bool = True
