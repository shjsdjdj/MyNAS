import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api import assets, auth, backup, photos, scan, settings, system, trash
from backend.core.security import RateLimitExceeded
from backend.db.database import initialize_database
from backend.services.asset_service import AssetForbidden, ensure_root_folders
from backend.services.auth_service import ensure_default_admin
from backend.services.backup_service import start_scheduler, stop_scheduler
from backend.services.scan_service import import_legacy_storage, run_disk_scan, start_default_storage_scan, start_scan_scheduler
from backend.services.settings_service import ensure_default_storage


_security_log = logging.getLogger("mynas.security")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.initialize_storage()
    initialize_database()
    admin = ensure_default_admin()
    ensure_root_folders(admin["id"])
    ensure_default_storage(admin["id"])
    if config.ADMIN_PASSWORD == "admin":
        _security_log.warning(
            "[SECURITY] 管理员仍使用默认密码 'admin'！"
            "请设置环境变量 MYNAS_ADMIN_PASSWORD 或登录后修改密码。"
        )
    if config.SCAN_ON_STARTUP:
        import_legacy_storage(admin["id"])
        start_default_storage_scan(admin["id"])
    start_scheduler()
    start_scan_scheduler(admin["id"])
    yield
    stop_scheduler()


app = FastAPI(
    title="MyNAS Secure API", version="3.1.0",
    docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(AssetForbidden)
def asset_forbidden(_request: Request, exc: AssetForbidden):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(FileNotFoundError)
def file_not_found(_request: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(FileExistsError)
def file_exists(_request: Request, exc: FileExistsError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def invalid_request(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded(_request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"登录尝试过多，请 {exc.retry_after} 秒后重试"},
        headers={"Retry-After": str(exc.retry_after)},
    )


app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(photos.router)
app.include_router(photos.asset_router)
app.include_router(photos.assets_router)
app.include_router(backup.router)
app.include_router(system.router)
app.include_router(trash.router)
app.include_router(settings.router)
app.include_router(scan.router)

if os.path.isdir("dist"):
    _dist_root = Path("dist").resolve()
    app.mount("/assets", StaticFiles(directory=_dist_root / "assets"), name="static")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_spa(spa_path: str):
        if spa_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_dist_root / spa_path).resolve()
        if _dist_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist_root / "index.html")
