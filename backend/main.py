import logging
import os
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api import assets, auth, backup, photos, scan, settings, system, trash
from backend.api.dependencies import current_user
from backend.core.security import COOKIE_NAME, RateLimitExceeded, client_ip, global_rate_limiter
from backend.db.database import initialize_database
from backend.services.asset_service import AssetForbidden, ensure_root_folders
from backend.services.auth_service import ensure_default_admin
from backend.services.backup_service import start_scheduler, stop_scheduler
from backend.services.scan_service import import_legacy_storage, run_disk_scan, start_default_storage_scan, start_scan_scheduler
from backend.services.settings_service import ensure_default_storage


_security_log = logging.getLogger("mynas.security")
# Only true public endpoints bypass the cookie-auth gate at the middleware
# boundary. Every other /api/* route requires an authenticated session.
_PUBLIC_API_PATHS = frozenset({"/api/auth/login"})


def _error_response(status_code: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def _safe_http_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


class RequestSizeLimitMiddleware:
    """Reject oversized requests before FastAPI parses or buffers their bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        limit = config.MAX_UPLOAD_BYTES + 1024 * 1024 if path == "/api/upload" else config.MAX_REQUEST_BYTES
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limit:
                    await _error_response(413, "request_too_large", "Request body is too large")(scope, receive, send)
                    return
            except ValueError:
                await _error_response(400, "invalid_request", "Invalid request")(scope, receive, send)
                return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail="Request body is too large")
            return message

        await self.app(scope, limited_receive, send)


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
    title="MyNAS Secure API", version="3.1.1",
    docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
)
app.add_middleware(RequestSizeLimitMiddleware)


@app.middleware("http")
async def api_security_boundary(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and (path.startswith("/api/") or path == "/health"):
        try:
            global_rate_limiter.check(client_ip(request))
        except RateLimitExceeded as exc:
            return _error_response(
                429, "rate_limited", "Too many requests", {"Retry-After": str(exc.retry_after)}
            )
    if request.method != "OPTIONS" and path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return _error_response(401, "unauthorized", "Authentication required")
        try:
            current_user(cookie_token=token)
        except HTTPException:
            return _error_response(401, "unauthorized", "Authentication required")
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if config.ENVIRONMENT == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(AssetForbidden)
def asset_forbidden(_request: Request, exc: AssetForbidden):
    return _error_response(403, "forbidden", "Access denied")


@app.exception_handler(FileNotFoundError)
def file_not_found(_request: Request, exc: FileNotFoundError):
    return _error_response(404, "not_found", "Resource not found")


@app.exception_handler(FileExistsError)
def file_exists(_request: Request, exc: FileExistsError):
    return _error_response(409, "conflict", "Resource conflict")


@app.exception_handler(ValueError)
def invalid_request(_request: Request, exc: ValueError):
    return _error_response(400, "invalid_request", "Invalid request")


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded(_request: Request, exc: RateLimitExceeded):
    return _error_response(429, "rate_limited", "Too many requests", {"Retry-After": str(exc.retry_after)})


@app.exception_handler(HTTPException)
def http_error(_request: Request, exc: HTTPException):
    code = "unauthorized" if exc.status_code == 401 else "forbidden" if exc.status_code == 403 else "http_error"
    return _error_response(exc.status_code, code, _safe_http_message(exc.status_code), exc.headers)


@app.exception_handler(RequestValidationError)
def validation_error(_request: Request, _exc: RequestValidationError):
    return _error_response(422, "validation_error", "Request validation failed")


@app.exception_handler(Exception)
def unhandled_error(_request: Request, _exc: Exception):
    _security_log.exception("Unhandled request failure")
    return _error_response(500, "internal_error", "Internal server error")


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


@app.get("/health", include_in_schema=False)
def public_health():
    """Unauthenticated liveness probe for external monitors / load balancers.

    Returns a fixed, intentionally-minimal JSON shape and leaks no internal state.
    """
    return {"status": "ok"}


if os.path.isdir("dist"):
    _dist_root = Path("dist").resolve()
    app.mount("/assets", StaticFiles(directory=_dist_root / "assets"), name="static")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_spa(spa_path: str):
        segments = {part.lower() for part in Path(spa_path).parts}
        sensitive_segments = {"config", "storage", "thumbnails", "backup", "users", "logs", "temp"}
        if spa_path.startswith("api/") or segments & sensitive_segments or spa_path.lower().endswith((".db", ".key", ".env")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_dist_root / spa_path).resolve()
        if _dist_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist_root / "index.html")
