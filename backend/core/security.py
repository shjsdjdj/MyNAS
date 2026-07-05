import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import Request

from backend import config

COOKIE_NAME = "mynas_token"
PASSWORD_ITERATIONS = 600_000
ALLOWED_MIME_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
    "video/mp4": (),
}
BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".js", ".html", ".htm", ".vbs", ".scr"}
MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "video/mp4": {".mp4"},
    "application/pdf": {".pdf"},
}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def jwt_secret() -> str:
    if not config.JWT_SECRET_PATH.exists():
        config.JWT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.JWT_SECRET_PATH.write_text(secrets.token_urlsafe(64), encoding="utf-8")
    return config.JWT_SECRET_PATH.read_text(encoding="utf-8").strip()


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id), "username": username, "iat": now,
        "exp": now + timedelta(hours=config.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, jwt_secret(), algorithms=[config.JWT_ALGORITHM])


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    candidate = peer
    if peer in {"127.0.0.1", "::1"}:
        cf_ip = request.headers.get("cf-connecting-ip")
        x_forwarded = request.headers.get("x-forwarded-for")
        
        if cf_ip:
            candidate = cf_ip.strip()
        elif x_forwarded:
            candidate = x_forwarded.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


def safe_display_filename(filename: str | None) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    if not name:
        name = "upload"
    return name[:255]


def validate_upload(filename: str, content_type: str | None, header: bytes):
    extension = Path(filename).suffix.lower()
    if extension in BLOCKED_EXTENSIONS:
        raise ValueError("禁止上传可执行或脚本文件")
    mime = (content_type or "").lower().split(";", 1)[0].strip()
    if mime not in ALLOWED_MIME_TYPES:
        raise ValueError("仅允许 JPEG、PNG、MP4 和 PDF 文件")
    if extension not in MIME_EXTENSIONS[mime]:
        raise ValueError("文件扩展名与声明类型不匹配")
    signatures = ALLOWED_MIME_TYPES[mime]
    if signatures and not any(header.startswith(signature) for signature in signatures):
        raise ValueError("文件内容与声明类型不匹配")
    if mime == "video/mp4" and not (len(header) >= 12 and header[4:8] == b"ftyp"):
        raise ValueError("文件内容不是有效的 MP4")


class RateLimitExceeded(Exception):
    """Raised when an IP exceeds the allowed login attempts."""
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


class LoginRateLimiter:
    """Sliding-window rate limiter for login attempts, keyed by IP."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        attempts = [t for t in self._failures.get(ip, []) if t > cutoff]
        if attempts:
            self._failures[ip] = attempts
        else:
            self._failures.pop(ip, None)
        return attempts

    def check(self, ip: str):
        """Raise *RateLimitExceeded* if *ip* has too many recent failures."""
        now = time.monotonic()
        with self._lock:
            attempts = self._prune(ip, now)
            if len(attempts) >= self.max_attempts:
                retry_after = int(attempts[0] + self.window_seconds - now) + 1
                raise RateLimitExceeded(retry_after)

    def record_failure(self, ip: str):
        now = time.monotonic()
        with self._lock:
            self._failures.setdefault(ip, []).append(now)
            # Prevent unbounded memory growth
            if len(self._failures) > 10_000:
                cutoff = now - self.window_seconds
                stale = [k for k, v in self._failures.items()
                         if not v or v[-1] < cutoff]
                for k in stale:
                    del self._failures[k]

    def clear(self, ip: str):
        with self._lock:
            self._failures.pop(ip, None)


login_rate_limiter = LoginRateLimiter()
