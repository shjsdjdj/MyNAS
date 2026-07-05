import os
from pathlib import Path

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
COOKIE_SECURE = os.getenv("MYNAS_COOKIE_SECURE", "true").lower() != "false"


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
