import pytest
from fastapi import Request

from backend import config
from backend.core.security import (
    COOKIE_NAME, GlobalRateLimiter, RateLimitExceeded, client_ip,
)
from tests.test_api import build_client, login, photos_root


def test_client_ip_extraction(monkeypatch):
    # Helper to mock request
    def make_request(host, headers):
        scope = {
            "type": "http",
            "client": (host, 12345),
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()]
        }
        return Request(scope)

    # 1. Normal client without proxy
    req = make_request("192.168.1.10", {})
    assert client_ip(req) == "192.168.1.10"

    # Proxy headers are ignored unless the immediate proxy is explicitly trusted.
    req = make_request("127.0.0.1", {"cf-connecting-ip": "203.0.113.1", "x-forwarded-for": "198.51.100.1"})
    assert client_ip(req) == "127.0.0.1"

    monkeypatch.setattr(config, "TRUSTED_PROXY_IPS", frozenset({"127.0.0.1"}))

    # 2. CF-Connecting-IP takes precedence for an explicitly trusted proxy.
    assert client_ip(req) == "203.0.113.1"

    # 3. X-Forwarded-For is used if CF-Connecting-IP is missing
    req = make_request("127.0.0.1", {"x-forwarded-for": "198.51.100.1, 10.0.0.1"})
    assert client_ip(req) == "198.51.100.1"

    # 4. Fallback to host if no headers
    req = make_request("127.0.0.1", {})
    assert client_ip(req) == "127.0.0.1"

    # 5. Untrusted proxy (not 127.0.0.1/::1) cannot spoof headers
    req = make_request("192.168.1.10", {"cf-connecting-ip": "203.0.113.1"})
    assert client_ip(req) == "192.168.1.10"


def test_global_rate_limiter_is_bounded():
    limiter = GlobalRateLimiter(max_requests=2, window_seconds=60)
    limiter.check("client")
    limiter.check("client")
    with pytest.raises(RateLimitExceeded):
        limiter.check("client")


def test_cookie_only_auth_and_logout_revocation(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        token = client.cookies.get(COOKIE_NAME)
        assert token
        client.cookies.clear()
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

        client.cookies.set(COOKIE_NAME, token)
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/auth/me").status_code == 401


def test_global_boundary_and_uniform_errors(tmp_path):
    client, _ = build_client(tmp_path)
    client.app.add_api_route("/api/unprotected-probe", lambda: {"unsafe": True}, methods=["GET"])
    with client:
        denied = client.get("/api/unprotected-probe")
        assert denied.status_code == 401
        assert denied.json() == {"error": {"code": "unauthorized", "message": "Authentication required"}}

        login(client)
        missing = client.get("/api/does-not-exist")
        assert missing.status_code == 404
        assert set(missing.json()) == {"error"}
        assert "detail" not in missing.json()


def test_request_size_limit_and_minimal_health(tmp_path, monkeypatch):
    monkeypatch.setenv("MYNAS_MAX_REQUEST_BYTES", "128")
    client, _ = build_client(tmp_path)
    with client:
        assert client.get("/health").json() == {"status": "ok"}
        login(client)
        root_id = photos_root(client)
        response = client.post("/api/assets/folder", json={"parent_id": root_id, "name": "x" * 200})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"


def test_cors_rejects_unknown_origin(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        response = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers
        assert client.get("/Config/mynas.db").status_code == 404
