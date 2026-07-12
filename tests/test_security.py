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


def test_request_size_limit_and_safe_health(tmp_path, monkeypatch):
    monkeypatch.setenv("MYNAS_MAX_REQUEST_BYTES", "128")
    client, _ = build_client(tmp_path)
    with client:
        health = client.get("/health")
        assert health.status_code == 200
        assert set(health.json()) == {"status", "backend", "database", "storage", "version", "uptime_seconds"}
        assert health.json()["status"] == "ok"
        assert health.json()["backend"] == "running"
        assert health.json()["uptime_seconds"] >= 0
        assert not {"path", "storage_path", "database_path", "token", "user_id", "network"} & set(health.json())
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


def test_network_status_uses_configured_origin_not_request_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("MYNAS_PUBLIC_BASE_URL", "https://nas.example.com")
    client, _ = build_client(tmp_path)
    from backend import config
    from backend.services import system_service

    with client:
        assert client.get("/api/network").status_code == 401
        login(client)
        token = client.cookies.get(COOKIE_NAME)
        monkeypatch.setattr(config, "COOKIE_SECURE", True)
        monkeypatch.setattr(system_service, "_tunnel_status", lambda: {"state": "healthy"})
        response = client.get("/api/network", headers={
            "Host": "evil.example",
            "CF-Connecting-IP": "203.0.113.77",
            "Cookie": f"{COOKIE_NAME}={token}",
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "public"
        assert payload["url"] == "https://nas.example.com"
        assert payload["public_url"] == "https://nas.example.com"
        assert payload["local_url"] == "http://127.0.0.1:8000"
        assert payload["public_access"] == {"state": "connected", "secure": True}
        assert payload["tunnel"] == {"state": "healthy"}
        assert payload["configured_by"] == "environment"
        assert payload["auth_required"] is True
        assert payload["checked_at"]
        assert "evil.example" not in response.text
        assert "storage_path" not in response.text


def test_network_status_defaults_to_local_only(tmp_path, monkeypatch):
    monkeypatch.delenv("MYNAS_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("MYNAS_PUBLIC_URL", raising=False)
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        response = client.get("/api/network")
        assert response.status_code == 200
        assert response.json()["mode"] == "localhost"
        assert response.json()["public_access"]["state"] == "local_only"


def test_network_status_distinguishes_configured_lan_and_local_urls(tmp_path, monkeypatch):
    from urllib.parse import urlparse
    from backend import config

    client, _ = build_client(tmp_path)
    with client:
        login(client)
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://127.0.0.1:8000")
        monkeypatch.setattr(config, "PARSED_PUBLIC_BASE_URL", urlparse("http://127.0.0.1:8000"))
        assert client.get("/api/network").json()["public_access"]["state"] == "local_only"

        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://192.168.1.10:8000")
        monkeypatch.setattr(config, "PARSED_PUBLIC_BASE_URL", urlparse("http://192.168.1.10:8000"))
        assert client.get("/api/network").json()["public_access"]["state"] == "lan_only"


def test_network_metrics_endpoint_must_be_loopback(monkeypatch):
    from backend import config
    from backend.services import system_service

    monkeypatch.setattr(config, "TUNNEL_METRICS_URL", "http://192.168.1.2:20241/metrics")
    assert system_service._metrics_urls() == ()

    monkeypatch.setattr(config, "TUNNEL_METRICS_URL", "http://127.0.0.1:20241/metrics")
    assert system_service._metrics_urls() == ("http://127.0.0.1:20241/metrics",)


def test_network_status_parses_local_cloudflared_metrics(monkeypatch):
    from backend.services import system_service

    class MetricsResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'cloudflared_tunnel_ha_connections{connection="0"} 1\n'

    monkeypatch.setattr(system_service, "_metrics_urls", lambda: ("http://127.0.0.1:20241/metrics",))
    monkeypatch.setattr(system_service, "urlopen", lambda *_args, **_kwargs: MetricsResponse())
    status = system_service._tunnel_status()
    assert status["state"] == "healthy"
    assert status["connections"] == 1
    assert status["reason"] is None
    assert status["last_heartbeat"]


def test_network_status_sums_all_cloudflared_connections(monkeypatch):
    from backend.services import system_service

    class MetricsResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return (
                b'cloudflared_tunnel_ha_connections{connection="0"} 0\n'
                b'cloudflared_tunnel_ha_connections{connection="1"} 2\n'
            )

    monkeypatch.setattr(system_service, "_metrics_urls", lambda: ("http://127.0.0.1:20241/metrics",))
    monkeypatch.setattr(system_service, "urlopen", lambda *_args, **_kwargs: MetricsResponse())
    status = system_service._tunnel_status()
    assert status["state"] == "healthy"
    assert status["connections"] == 2


def test_health_reports_sanitized_database_failure(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from backend.services import system_service

    client, _ = build_client(tmp_path)

    @contextmanager
    def failed_connection(*_args, **_kwargs):
        raise RuntimeError("secret database detail")
        yield

    with client:
        monkeypatch.setattr(system_service, "connection", failed_connection)
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["reason"] == "database_error"
        assert response.json()["database"] == "error"
        assert "secret" not in response.text
        assert "path" not in response.text.lower()


def test_health_reports_sanitized_storage_failure(tmp_path, monkeypatch):
    from backend.services import system_service

    client, _ = build_client(tmp_path)
    with client:
        monkeypatch.setattr(system_service.shutil, "disk_usage", lambda *_: (_ for _ in ()).throw(OSError("private path")))
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["reason"] == "storage_unavailable"
        assert response.json()["storage"] == "unavailable"
        assert "private" not in response.text
