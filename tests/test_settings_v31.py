import sqlite3

from backend.core.security import hash_password
from tests.test_api import build_client, login


def test_preferences_and_username_are_persisted(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        defaults = client.get("/api/settings/preferences")
        assert defaults.status_code == 200
        assert defaults.json()["language"] == "zh"
        saved = client.patch("/api/settings/preferences", json={
            "language": "en", "theme": "light", "default_home": "timeline",
            "default_upload_directory": "Documents", "photo_sort": "uploaded_desc",
        })
        assert saved.status_code == 200
        assert client.get("/api/settings/preferences").json()["default_home"] == "timeline"

        renamed = client.patch("/api/settings/account/username", json={"username": "cloud-admin"})
        assert renamed.status_code == 200
        assert client.get("/api/auth/me").json()["username"] == "cloud-admin"
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute("SELECT value FROM settings WHERE key='preferences_1'").fetchone()


def test_storage_locations_crud_default_capacity_and_ownership(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        initial = client.get("/api/settings/storage").json()["items"]
        assert len(initial) == 1 and initial[0]["is_default"] is True
        assert initial[0]["path"] == str(root)

        created = client.post("/api/settings/storage", json={"name": "Photo Archive", "path": "F:\\Photos"})
        assert created.status_code == 200
        location = created.json()
        assert location["capacity"]["available"] is False
        updated = client.patch(f"/api/settings/storage/{location['id']}", json={"name": "Photo Vault", "path": "F:\\Archive"})
        assert updated.status_code == 200 and updated.json()["name"] == "Photo Vault"
        assert client.post(f"/api/settings/storage/{location['id']}/default").status_code == 200
        assert client.delete(f"/api/settings/storage/{initial[0]['id']}").status_code == 200
        assert client.post("/api/settings/storage", json={"name": "Bad", "path": "..\\Windows"}).status_code == 400

        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO users(username,password_hash,is_admin,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("settings-viewer", hash_password("ViewerPass123"), 0, "2026-01-01", "2026-01-01"),
            )
            db.commit()
        login(client, "settings-viewer", "ViewerPass123")
        assert client.patch(f"/api/settings/storage/{location['id']}", json={"name": "stolen"}).status_code == 403


def test_backup_daily_settings_and_system_information(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        backup = client.patch("/api/settings/backup", json={
            "directory": "G:\\Backup", "enabled": True, "daily_time": "03:30",
        })
        assert backup.status_code == 200
        assert backup.json()["enabled"] is True and backup.json()["daily_time"] == "03:30"
        assert client.post("/api/settings/backup/run").status_code == 200
        assert client.patch("/api/settings/backup", json={"enabled": False}).status_code == 200

        system = client.get("/api/settings/system")
        assert system.status_code == 200
        data = system.json()
        assert data["mynas_version"] == "3.1.0"
        assert data["python_version"] and data["sqlite_version"]
        assert data["asset_count"] >= 5
        assert "storage_usage" in data
