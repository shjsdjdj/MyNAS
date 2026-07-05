"""Backward-compatible imports for v1 callers."""

from backend.db.database import (
    connection,
    get_setting,
    initialize_database,
    recent_activities,
    record_activity,
    set_setting,
    utc_now,
)

__all__ = [
    "connection", "get_setting", "initialize_database", "recent_activities",
    "record_activity", "set_setting", "utc_now",
]
