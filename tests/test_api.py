import importlib
import io
import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def build_client(tmp_path: Path, admin_password="TestPassword123"):
    os.environ["MYNAS_ROOT"] = str(tmp_path / "MyNAS")
    os.environ["MYNAS_ADMIN_PASSWORD"] = admin_password
    os.environ["MYNAS_SCAN_ON_STARTUP"] = "false"
    os.environ["MYNAS_COOKIE_SECURE"] = "false"
    import backend.config
    import backend.main
    importlib.reload(backend.config)
    app_module = importlib.reload(backend.main)
    return TestClient(app_module.app), backend.config.DATA_ROOT


def login(client: TestClient, username="admin", password="TestPassword123"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def photos_root(client: TestClient) -> str:
    dashboard = client.get("/api/dashboard").json()
    return next(item["id"] for item in dashboard["categories"] if item["name"] == "Photos")


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (16, 12), "#4b68f4").save(stream, "PNG")
    return stream.getvalue()


def test_no_token_means_zero_access(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/dashboard").status_code == 401
        assert client.get("/api/assets").status_code == 401
        assert client.get("/api/assets/list").status_code == 401
        assert client.get(f"/api/asset/{uuid4()}").status_code == 401
        assert client.post("/api/upload").status_code == 401


def test_every_non_login_api_route_denies_anonymous_access(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        checked = []
        for route in client.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api") or path == "/api/auth/login":
                continue
            concrete_path = path.replace("{asset_id}", str(uuid4()))
            methods = sorted(set(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"})
            for method in methods:
                response = client.request(method, concrete_path)
                assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
                checked.append((method, path))
        assert len(checked) >= 20


def test_login_cookie_and_audit_log(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        assert client.post("/api/auth/login", json={"username": "admin' OR 1=1 --", "password": "x"}).status_code == 401
        result = login(client)
        assert result["user"]["username"] == "admin"
        assert client.get("/api/auth/me").status_code == 200
        logs = client.get("/api/audit-logs").json()["items"]
        assert any(row["action"] == "login" and row["ip_address"] for row in logs)


def test_secure_upload_uuid_storage_and_no_path_leak(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        response = client.post(
            "/api/upload",
            data={"parent_id": root_id},
            files={"files": ("family.png", png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        asset = response.json()["uploaded"][0]
        UUID(asset["id"])
        assert "storage_path" not in asset
        assert "thumbnail_storage_path" not in asset
        storage_file = root / "Storage" / "1" / asset["id"]
        assert storage_file.is_file()
        assert storage_file.name == asset["id"]
        assert not (root / "Storage" / "1" / "family.png").exists()
        listing = client.get("/api/assets/list", params={"parent_id": root_id}).json()
        assert "storage_path" not in str(listing)


def test_upload_rejects_executable_spoof_and_oversized_type(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        executable = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("payload.exe", b"%PDF-1.4 malicious", "application/pdf")},
        )
        assert executable.status_code == 400
        spoofed = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("fake.png", b"not a png", "image/png")},
        )
        assert spoofed.status_code == 400
        mismatch = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("fake.txt", b"%PDF-1.4", "application/pdf")},
        )
        assert mismatch.status_code == 400
        assert list((root / "Storage" / "1").glob("*"))
        assert not any(path.is_file() for path in (root / "Storage" / "1").glob("*"))


def test_download_delete_by_asset_id_and_audit(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        uploaded = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("photo.png", png_bytes(), "image/png")},
        ).json()["uploaded"][0]
        asset_id = uploaded["id"]
        download = client.get(f"/api/asset/{asset_id}")
        assert download.status_code == 200
        assert download.content == png_bytes()
        assert client.get("/api/files", params={"path": "../../Windows/win.ini"}).status_code == 404
        assert client.delete(f"/api/asset/{asset_id}").status_code == 200
        assert client.get(f"/api/asset/{asset_id}").status_code == 404
        assert (root / "Storage" / "1" / asset_id).exists()
        assert client.delete(f"/api/trash/{asset_id}/permanent").status_code == 200
        assert not (root / "Storage" / "1" / asset_id).exists()
        actions = [row["action"] for row in client.get("/api/audit-logs").json()["items"]]
        assert "upload" in actions and "download" in actions and "delete" in actions


def test_cross_user_asset_access_is_forbidden(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        asset_id = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("private.pdf", b"%PDF-1.4 private", "application/pdf")},
        ).json()["uploaded"][0]["id"]
        from backend.core.security import hash_password
        database = sqlite3.connect(root / "Config" / "mynas.db")
        database.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("other", hash_password("other-password"), 0, "2026-01-01", "2026-01-01"),
        )
        database.commit()
        database.close()
        login(client, "other", "other-password")
        assert client.get(f"/api/asset/{asset_id}").status_code == 404
        assert client.delete(f"/api/asset/{asset_id}").status_code == 404


def test_thumbnail_timeline_and_database_driven_listing(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        asset = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("timeline.png", png_bytes(), "image/png")},
        ).json()["uploaded"][0]
        # Thumbnail generation runs in the background, so thumbnail_url is None in the upload response.
        assert client.get(f"/api/photos/{asset['id']}/thumbnail").status_code == 200
        groups = client.get("/api/photos/timeline").json()["groups"]
        assert groups and groups[0]["items"][0]["id"] == asset["id"]
        # A rogue disk file is invisible because listings are database-driven.
        (root / "Storage" / "1" / "rogue").write_bytes(b"hidden")
        listing = client.get("/api/assets/list", params={"parent_id": root_id}).json()["items"]
        assert all(item["id"] != "rogue" and item["filename"] != "rogue" for item in listing)


def test_incremental_backup_uses_assets_not_input_paths(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        uploaded = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("backup.pdf", b"%PDF-1.4 backup", "application/pdf")},
        ).json()["uploaded"][0]
        external_backup = tmp_path / "ExternalBackup"
        from backend.db.database import set_setting
        set_setting("backup_directory_1", str(external_backup))
        first = client.post("/api/backups/run").json()
        second = client.post("/api/backups/run").json()
        assert first["files_copied"] == 1
        assert second["files_copied"] == 0
        backup_files = [
            path for path in (external_backup / "1").rglob("*")
            if path.is_file() and path.name != "manifest.json"
        ]
        assert len(backup_files) == 1
        assert not any(
            path.is_file() for path in (root / "Backup").rglob("*")
        )
        # A local disk change is detected by recomputing SHA-256, not by trusting stale DB metadata.
        (root / "Storage" / "1" / uploaded["id"]).write_bytes(b"%PDF-1.4 changed")
        third = client.post("/api/backups/run").json()
        assert third["files_copied"] == 1
        assert client.post("/api/backups/run", json={"source_path": "C:\\Windows"}).status_code == 200
        assert "source_path" not in client.post("/api/backups/run", json={"source_path": "../../"}).json()


def test_backup_failure_leaves_no_partial_snapshot_or_entries(tmp_path, monkeypatch):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("atomic.pdf", b"%PDF-1.4 atomic", "application/pdf")},
        )
        external_backup = tmp_path / "AtomicBackup"
        from backend.db.database import set_setting
        import backend.services.backup_service as backups
        set_setting("backup_directory_1", str(external_backup))
        monkeypatch.setattr(backups.shutil, "copy2", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")))

        with pytest.raises(OSError, match="copy failed"):
            backups.run_incremental_backup(1)

        assert not list((external_backup / "1").glob("*"))
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute("SELECT COUNT(*) FROM backup_entries").fetchone()[0] == 0
            assert db.execute(
                "SELECT status FROM backup_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()[0] == "failed"


def test_backup_schedule_is_persisted_and_audited(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        response = client.post("/api/backups/schedule", json={"interval_minutes": 30, "enabled": True})
        assert response.status_code == 200
        assert response.json() == {"user_id": 1, "interval_minutes": 30, "enabled": True}
        actions = [row["action"] for row in client.get("/api/audit-logs").json()["items"]]
        assert "backup_schedule" in actions
        assert client.post("/api/backups/schedule", json={"interval_minutes": 30, "enabled": False}).status_code == 200


def test_secure_route_surface_and_filename_sanitization(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        paths = {route.path for route in client.app.routes if hasattr(route, "path")}
        assert "/api/files" not in paths
        assert "/api/files/download" not in paths
        assert "/api/files/preview" not in paths
        assert "/docs" not in paths and "/openapi.json" not in paths
        login(client)
        root_id = photos_root(client)
        response = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("../../injected.pdf", b"%PDF-1.4 safe", "application/pdf")},
        )
        assert response.status_code == 200
        asset = response.json()["uploaded"][0]
        assert asset["filename"] == "injected.pdf"
        assert (root / "Storage" / "1" / asset["id"]).is_file()


def test_default_password_forces_change(tmp_path):
    """CRIT-1: default admin/admin must force password change before API access."""
    client, _ = build_client(tmp_path, admin_password="admin")
    with client:
        result = login(client, password="admin")
        assert result["password_change_required"] is True

        # Core APIs blocked with 403
        assert client.get("/api/dashboard").status_code == 403
        assert client.get("/api/assets/list").status_code == 403
        assert client.get("/api/health").status_code == 403
        assert client.post("/api/backups/run").status_code == 403
        assert client.get("/api/photos/timeline").status_code == 403
        assert client.get("/api/audit-logs").status_code == 403

        # Auth endpoints remain accessible
        assert client.get("/api/auth/me").status_code == 200

        # Reject "admin" as new password (Pydantic min_length=8 catches it first)
        bad = client.post("/api/auth/change-password", json={
            "current_password": "admin", "new_password": "admin",
        })
        assert bad.status_code == 422

        # Reject short password (Pydantic min_length=8)
        short = client.post("/api/auth/change-password", json={
            "current_password": "admin", "new_password": "short",
        })
        assert short.status_code == 422

        # Successful password change
        ok = client.post("/api/auth/change-password", json={
            "current_password": "admin", "new_password": "Str0ngP@ss!",
        })
        assert ok.status_code == 200

        # Core APIs now accessible
        assert client.get("/api/dashboard").status_code == 200
        assert client.get("/api/health").status_code == 200

        # Re-login with new password — no forced change
        result2 = client.post("/api/auth/login", json={
            "username": "admin", "password": "Str0ngP@ss!",
        }).json()
        assert result2["password_change_required"] is False
        assert client.get("/api/dashboard").status_code == 200


def test_login_response_contains_no_token(tmp_path):
    """HIGH-1: login response must not leak the raw JWT."""
    client, _ = build_client(tmp_path)
    with client:
        result = login(client)
        assert "access_token" not in result
        assert result["token_type"] == "cookie"
        # Cookie-based auth still works
        assert client.get("/api/auth/me").status_code == 200
        assert client.get("/api/dashboard").status_code == 200


def test_rejected_upload_never_creates_file(tmp_path):
    """HIGH-2: invalid uploads must be rejected before any bytes hit disk."""
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        storage = root / "Storage" / "1"
        files_before = {p for p in storage.rglob("*") if p.is_file()} if storage.exists() else set()
        # Spoofed PNG header
        client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("evil.png", b"not a real png image data here!", "image/png")},
        )
        # Executable with PDF mime
        client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("hack.exe", b"%PDF-1.4 malicious payload", "application/pdf")},
        )
        files_after = {p for p in storage.rglob("*") if p.is_file()} if storage.exists() else set()
        orphans = files_after - files_before
        assert not orphans, f"Rejected uploads left orphan files on disk: {orphans}"


def test_admin_global_audit_logs(tmp_path):
    """HIGH-4: admins see all users' logs; non-admins get 403."""
    client, root = build_client(tmp_path)
    with client:
        login(client)
        # Admin can access global logs
        resp = client.get("/api/admin/audit-logs")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert isinstance(items, list)
        assert any(row["action"] == "login" for row in items)

        # Create a non-admin user
        from backend.core.security import hash_password
        database = sqlite3.connect(root / "Config" / "mynas.db")
        database.execute(
            "INSERT INTO users(username,password_hash,is_admin,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("viewer", hash_password("ViewerPass123"), 0, "2026-01-01", "2026-01-01"),
        )
        database.commit()
        database.close()

        # Non-admin cannot access global logs
        login(client, "viewer", "ViewerPass123")
        assert client.get("/api/admin/audit-logs").status_code == 403
        # But can still see their own logs
        assert client.get("/api/audit-logs").status_code == 200
