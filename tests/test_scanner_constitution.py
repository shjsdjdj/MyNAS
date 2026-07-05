import sqlite3
from pathlib import Path
from uuid import uuid4

from tests.test_api import build_client, login


def test_scanner_indexes_unknown_and_duplicate_files_without_upload_validation(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        source = root / "Photos" / "nested"
        source.mkdir()
        (source / "program.exe").write_bytes(b"MZ scanner input")
        (source / "unknown.custom-type").write_bytes(b"unknown scanner input")
        (source / "duplicate-a.bin").write_bytes(b"same bytes")
        (source / "duplicate-b.bin").write_bytes(b"same bytes")

        import backend.services.scan_service as scanner

        assert not hasattr(scanner, "validate_upload")
        response = client.post("/api/assets/import-legacy")
        assert response.status_code == 200
        assert response.json() == {"imported": 4, "skipped_duplicates": 0, "errors": []}

        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            rows = db.execute(
                "SELECT filename,hash,storage_path FROM assets WHERE type!='folder' ORDER BY filename"
            ).fetchall()
        assert {row[0] for row in rows} == {
            "program.exe", "unknown.custom-type", "duplicate-a.bin", "duplicate-b.bin",
        }
        assert rows[0][1] == rows[1][1]
        assert all(Path(row[2]).is_file() for row in rows)
        assert len(list((root / "Storage" / "1").glob("*"))) > len(rows)
        assert sum(path.is_file() for path in (root / "Storage" / "1").glob("*")) == len(rows)


def test_scanner_rolls_back_copied_file_when_asset_creation_fails(tmp_path, monkeypatch):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        (root / "Documents" / "rollback.bin").write_bytes(b"rollback")

        import backend.services.scan_service as scanner

        monkeypatch.setattr(scanner, "create_file_asset", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("db failed")))
        result = scanner.import_legacy_storage(1)
        assert result["imported"] == 0
        assert result["errors"] == [{"name": "rollback.bin", "error": "db failed"}]
        assert not any(path.is_file() for path in (root / "Storage" / "1").glob("*"))
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute("SELECT COUNT(*) FROM assets WHERE type!='folder'").fetchone()[0] == 0


def test_startup_resumes_default_registered_storage_scan(tmp_path, monkeypatch):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        location_id = str(uuid4())
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute("UPDATE storage_locations SET is_default=0 WHERE user_id=1")
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Photo Disk','F:\\Photos',1,'2026-01-01','2026-01-01')",
                (location_id,),
            )

        import backend.services.scan_service as scanner

        calls = []
        monkeypatch.setattr(
            scanner,
            "start_background_scan",
            lambda user_id, selected_id: calls.append((user_id, selected_id)) or {"scan_started": True},
        )

        assert scanner.start_default_storage_scan(1) == {"scan_started": True}
        assert calls == [(1, location_id)]
