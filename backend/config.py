import os
import platform
import time
from pathlib import Path
from urllib.parse import urlparse

# Public deployment metadata and security controls.
VERSION = os.getenv("MYNAS_VERSION", "3.4.0")
# MYNAS_PUBLIC_URL remains supported for existing deployments.  The new name
# makes it explicit that this is a configured base URL, never a request Host.
PUBLIC_BASE_URL = os.getenv("MYNAS_PUBLIC_BASE_URL", os.getenv("MYNAS_PUBLIC_URL", "")).strip().rstrip("/")
PUBLIC_URL = PUBLIC_BASE_URL
TUNNEL_METRICS_URL = os.getenv("MYNAS_TUNNEL_METRICS_URL", "").strip()
ENVIRONMENT = os.getenv("MYNAS_ENV", "development").strip().lower()
# Process start timestamp (monotonic, for uptime only — never wall-clock sensitive).
START_MONOTONIC = time.monotonic()


def _default_data_root() -> Path:
    if platform.system() == "Windows":
        return Path(r"E:\MyNAS")
    return Path.home() / "MyNAS"


def _resolve_data_root() -> Path:
    configured_root = os.getenv("MYNAS_ROOT", "").strip()
    return Path(configured_root).expanduser() if configured_root else _default_data_root()


DATA_ROOT = _resolve_data_root()
DATA_DIRECTORIES = (
    "Photos", "Videos", "Documents", "Downloads", "Backup",
    "Users", "Config", "Logs", "Temp", "Thumbnails", "Storage",
)
INDEXED_DIRECTORIES = ("Photos", "Videos", "Documents", "Downloads", "Backup")
DATABASE_PATH = DATA_ROOT / "Config" / "mynas.db"
JWT_SECRET_PATH = DATA_ROOT / "Config" / "jwt-secret.key"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("MYNAS_JWT_EXPIRE_HOURS", "24"))
ADMIN_USERNAME = os.getenv("MYNAS_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("MYNAS_ADMIN_PASSWORD", "admin")
SCAN_ON_STARTUP = os.getenv("MYNAS_SCAN_ON_STARTUP", "true").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MYNAS_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_REQUEST_BYTES = int(os.getenv("MYNAS_MAX_REQUEST_BYTES", str(1024 * 1024)))
RATE_LIMIT_REQUESTS = int(os.getenv("MYNAS_RATE_LIMIT_REQUESTS", "300"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("MYNAS_RATE_LIMIT_WINDOW_SECONDS", "60"))
COOKIE_SECURE = os.getenv("MYNAS_COOKIE_SECURE", "true").lower() != "false"
JWT_LEEWAY_SECONDS = int(os.getenv("MYNAS_JWT_LEEWAY_SECONDS", "30"))
TRUSTED_PROXY_IPS = frozenset(
    value.strip() for value in os.getenv("MYNAS_TRUSTED_PROXY_IPS", "").split(",") if value.strip()
)

def _parse_public_base_url(value: str):
    if not value:
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError("MYNAS_PUBLIC_BASE_URL must be an origin such as https://nas.example.com")
    return parsed


PARSED_PUBLIC_BASE_URL = _parse_public_base_url(PUBLIC_BASE_URL)
_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if PARSED_PUBLIC_BASE_URL:
    _default_origins.append(f"{PARSED_PUBLIC_BASE_URL.scheme}://{PARSED_PUBLIC_BASE_URL.netloc}")
CORS_ORIGINS = tuple(dict.fromkeys(
    value.strip() for value in os.getenv("MYNAS_CORS_ORIGINS", ",".join(_default_origins)).split(",") if value.strip()
))

if ENVIRONMENT == "production" and ("*" in CORS_ORIGINS or not COOKIE_SECURE):
    raise RuntimeError("Production requires explicit CORS origins and secure cookies")


def initialize_storage() -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    for name in DATA_DIRECTORIES:
        (DATA_ROOT / name).mkdir(parents=True, exist_ok=True)
    return DATA_ROOT


def safe_path(relative: str = "") -> Path:
    candidate = (DATA_ROOT / relative).resolve()
    root = DATA_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("路径超出 NAS 数据目录")
    return candidate
