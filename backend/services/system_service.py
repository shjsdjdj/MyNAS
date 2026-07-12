import ipaddress
import os
import re
import socket
import shutil
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlparse

from backend import config
from backend.db.database import connection, recent_audit_logs, utc_now
from backend.models.asset import Asset
from backend.services.asset_service import dashboard_categories, public_asset
from backend.services.backup_service import backup_logs
from backend.utils.files import size_label


def health_status(include_network: bool = False) -> dict:
    """Return a sanitized readiness snapshot without paths or exception details."""
    database_state = "ready"
    storage_state = "available"
    reason = None

    try:
        with connection(timeout_seconds=1.0) as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:  # Readiness must report failure without leaking internals.
        database_state = "error"
        reason = "database_error"

    try:
        if not config.DATA_ROOT.is_dir() or not os.access(config.DATA_ROOT, os.R_OK | os.W_OK):
            raise OSError("storage unavailable")
        shutil.disk_usage(config.DATA_ROOT)
    except (OSError, ValueError):
        storage_state = "unavailable"
        if reason is None:
            reason = "storage_unavailable"

    result = {
        "status": "ok" if reason is None else "error",
        "backend": "running",
        "database": database_state,
        "storage": storage_state,
        "version": config.VERSION,
        "uptime_seconds": max(0, int(time.monotonic() - config.START_MONOTONIC)),
    }
    if reason:
        result["reason"] = reason
    if include_network:
        result["network"] = network_status()
    return result


def dashboard(user_id: int) -> dict:
    disk = shutil.disk_usage(config.DATA_ROOT)
    with connection() as conn:
        counts = conn.execute(
            "SELECT COUNT(*) asset_count, SUM(type='image') photo_count, SUM(type='video') video_count, "
            "SUM(type='file') file_count, SUM(is_favorite=1) favorite_count "
            "FROM assets WHERE user_id=? AND is_deleted=0", (user_id,),
        ).fetchone()
        recent_rows = conn.execute(
            "SELECT * FROM assets WHERE user_id=? AND type='image' AND is_deleted=0 ORDER BY created_at DESC LIMIT 6",
            (user_id,),
        ).fetchall()
    latest_backup = backup_logs(user_id, 1)
    return {
        "device_name": _device_name(),
        "data_root": "MyNAS Secure Storage",
        "disk": {
            "total": disk.total, "used": disk.used, "free": disk.free,
            "percent": round(disk.used / disk.total * 100, 1),
            "total_label": size_label(disk.total), "used_label": size_label(disk.used),
            "free_label": size_label(disk.free),
        },
        "categories": dashboard_categories(user_id),
        "stats": {
            "asset_count": counts["asset_count"] or 0,
            "photo_count": counts["photo_count"] or 0,
            "video_count": counts["video_count"] or 0,
            "file_count": counts["file_count"] or 0,
            "favorite_count": counts["favorite_count"] or 0,
        },
        "recent_photos": [public_asset(Asset.from_row(row)) for row in recent_rows],
        "backup": latest_backup[0] if latest_backup else {"status": "never", "finished_at": None},
        "health": health_status(),
        "network": network_status(),
        "activities": [
            {"id": row["id"], "action": row["action"], "target": row["asset_id"] or "", "detail": row["detail"], "created_at": row["created_at"]}
            for row in recent_audit_logs(user_id, 8)
        ],
    }


def network_status() -> dict:
    """Return configured access state without consulting request headers.

    A running cloudflared connector exposes local Prometheus metrics.  This
    verifies only the local connector, not remote DNS or an external client,
    and does not require Cloudflare credentials or API access.
    """
    base_url = config.PUBLIC_BASE_URL
    local_url = "http://127.0.0.1:8000"
    checked_at = utc_now()
    common = {
        "local_url": local_url,
        "lan_url": None,
        "public_url": None,
        "checked_at": checked_at,
        "configured_by": "environment",
        "auth_required": True,
    }
    if not base_url or not config.PARSED_PUBLIC_BASE_URL:
        return {
            **common,
            "mode": "localhost",
            "url": None,
            "public_access": {"state": "local_only", "secure": False},
            "tunnel": {"state": "not_configured"},
        }

    mode = _access_mode(config.PARSED_PUBLIC_BASE_URL.hostname or "")
    is_secure = config.PARSED_PUBLIC_BASE_URL.scheme == "https"
    if mode != "public":
        return {
            **common,
            "mode": mode,
            "url": base_url,
            "lan_url": base_url if mode == "lan" else None,
            "public_access": {"state": "local_only" if mode == "localhost" else "lan_only", "secure": is_secure},
            "tunnel": {"state": "not_configured"},
        }

    tunnel = _tunnel_status()
    is_connected = is_secure and config.COOKIE_SECURE and tunnel["state"] == "healthy"
    public_access = {"state": "connected" if is_connected else "offline", "secure": is_secure}
    if not is_connected:
        public_access["reason"] = (
            "https_required" if not is_secure
            else "secure_cookie_required" if not config.COOKIE_SECURE
            else "tunnel_offline"
        )
    return {
        **common,
        "mode": "public",
        "url": base_url,
        "public_url": base_url,
        "public_access": public_access,
        "tunnel": tunnel,
    }


def _access_mode(host: str) -> str:
    if host.lower() == "localhost":
        return "localhost"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "public"
    return "localhost" if address.is_loopback else "lan"


def _tunnel_status() -> dict:
    for metrics_url in _metrics_urls():
        try:
            with urlopen(metrics_url, timeout=0.35) as response:  # nosec B310: validated loopback URLs only
                payload = response.read(512_000).decode("utf-8", errors="replace")
        except (OSError, URLError, ValueError):
            continue
        matches = re.findall(r"^cloudflared_tunnel_ha_connections(?:\{[^}]*\})?\s+([0-9.]+)", payload, re.MULTILINE)
        if matches:
            connections = sum(float(value) for value in matches)
            return {
                "state": "healthy" if connections > 0 else "offline",
                "connections": int(connections) if connections.is_integer() else connections,
                "reason": None if connections > 0 else "connector_no_connections",
                "last_heartbeat": utc_now(),
            }
        return {"state": "unknown", "reason": "metrics_missing"}
    return {"state": "offline", "reason": "metrics_unavailable"}


def _metrics_urls() -> tuple[str, ...]:
    if config.TUNNEL_METRICS_URL:
        parsed = urlparse(config.TUNNEL_METRICS_URL)
        try:
            is_loopback = parsed.hostname and ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname == "localhost"
        if parsed.scheme == "http" and is_loopback and parsed.path == "/metrics" and not parsed.query:
            return (config.TUNNEL_METRICS_URL,)
        return ()
    return tuple(f"http://127.0.0.1:{port}/metrics" for port in range(20241, 20246))


def _device_name() -> str:
    try:
        return socket.gethostname().strip() or "MyNAS Node"
    except OSError:
        return "MyNAS Node"
