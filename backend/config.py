import os
import time
from pathlib import Path
from urllib.parse import urlparse

# Public deployment metadata and security controls.
VERSION = os.getenv("MYNAS_VERSION", "v3.1.1")
PUBLIC_URL = os.getenv("MYNAS_PUBLIC_URL", "").strip()
ENVIRONMENT = os.getenv("MYNAS_ENV", "development").strip().lower()
# Process start timestamp (monotonic, for uptime only — never wall-clock sensitive).
START_MONOTONIC = time.monotonic()

DATA_ROOT = Path(os.getenv("MYNAS_ROOT", r"E:\MyNAS"))
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

_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if PUBLIC_URL:
    parsed_public_url = urlparse(PUBLIC_URL)
    if parsed_public_url.scheme in {"http", "https"} and parsed_public_url.netloc:
        _default_origins.append(f"{parsed_public_url.scheme}://{parsed_public_url.netloc}")
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
