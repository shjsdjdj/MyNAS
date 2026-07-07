import sqlite3
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

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
        assert response.json() == {
            "imported": 4, "updated": 0, "deleted": 0,
            "skipped_duplicates": 0, "errors": [],
        }

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
        configured_path = str(tmp_path / "ConfiguredPhotoSource")
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute("UPDATE storage_locations SET is_default=0 WHERE user_id=1")
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Photo Disk',?,1,'2026-01-01','2026-01-01')",
                (location_id, configured_path),
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


def test_registered_scanner_reconciles_modified_and_deleted_files_idempotently(tmp_path):
    client, root = build_client(tmp_path)
    source_root = tmp_path / "PhotoSource"
    source_root.mkdir()
    source_file = source_root / "photo.bin"
    source_file.write_bytes(b"version-one")
    location_id = str(uuid4())
    with client:
        login(client)
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Reconcile Source',?,0,'2026-01-01','2026-01-01')",
                (location_id, str(source_root)),
            )

        import backend.services.scan_service as scanner

        first = scanner._scan_registered_storage(1, location_id)
        second = scanner._scan_registered_storage(1, location_id)
        assert first["imported"] == 1
        assert second["imported"] == 0 and second["skipped_existing"] == 1

        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            before = db.execute(
                "SELECT id,hash,storage_path FROM assets WHERE filename='photo.bin' AND is_deleted=0"
            ).fetchone()
            assert db.execute(
                "SELECT COUNT(*) FROM assets WHERE filename='photo.bin' AND is_deleted=0"
            ).fetchone()[0] == 1

        source_file.write_bytes(b"version-two")
        modified = scanner._scan_registered_storage(1, location_id)
        assert modified["updated"] == 1
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            after = db.execute(
                "SELECT id,hash,storage_path FROM assets WHERE filename='photo.bin' AND is_deleted=0"
            ).fetchone()
        assert after[0] == before[0] and after[1] != before[1]
        assert Path(after[2]).read_bytes() == b"version-two"

        source_file.unlink()
        deleted = scanner._scan_registered_storage(1, location_id)
        assert deleted["deleted"] == 1
        assert scanner._scan_registered_storage(1, location_id)["deleted"] == 0
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute(
                "SELECT is_deleted FROM assets WHERE id=?", (after[0],)
            ).fetchone()[0] == 1


def test_linux_scanner_migrates_previous_case_folded_identity(tmp_path, monkeypatch):
    client, root = build_client(tmp_path)
    source_root = tmp_path / "LinuxCaseSource"
    source_root.mkdir()
    source_file = source_root / "Photo.BIN"
    source_file.write_bytes(b"case migration")
    location_id = str(uuid4())
    with client:
        login(client)
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Linux Case Source',?,0,'2026-01-01','2026-01-01')",
                (location_id, str(source_root)),
            )

        import backend.services.scan_service as scanner

        monkeypatch.setattr(scanner.platform, "system", lambda: "Windows")
        assert scanner._scan_registered_storage(1, location_id)["imported"] == 1
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            previous_id = db.execute(
                "SELECT id FROM assets WHERE filename='Photo.BIN' AND is_deleted=0"
            ).fetchone()[0]

        monkeypatch.setattr(scanner.platform, "system", lambda: "Linux")
        expected_id = scanner._scanner_asset_id(UUID(location_id), "Photo.BIN")
        assert expected_id != previous_id
        result = scanner._scan_registered_storage(1, location_id)
        assert result["imported"] == 0 and result["skipped_existing"] == 1
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            rows = db.execute(
                "SELECT id FROM assets WHERE filename='Photo.BIN' AND is_deleted=0"
            ).fetchall()
        assert rows == [(expected_id,)]

        source_file.unlink()
        assert scanner._scan_registered_storage(1, location_id)["deleted"] == 1


def test_legacy_scanner_is_idempotent(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        source = root / "Documents" / "once.bin"
        source.write_bytes(b"only once")

        import backend.services.scan_service as scanner

        first = scanner.import_legacy_storage(1)
        second = scanner.import_legacy_storage(1)
        assert first["imported"] == 1
        assert second["imported"] == 0
        assert second["skipped_duplicates"] == 1
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute(
                "SELECT COUNT(*) FROM assets WHERE filename='once.bin' AND is_deleted=0"
            ).fetchone()[0] == 1


def test_unavailable_registered_storage_never_mass_deletes_assets(tmp_path):
    client, root = build_client(tmp_path)
    source_root = tmp_path / "RemovableDrive"
    source_root.mkdir()
    (source_root / "keep.bin").write_bytes(b"keep active")
    location_id = str(uuid4())
    with client:
        login(client)
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Removable',?,0,'2026-01-01','2026-01-01')",
                (location_id, str(source_root)),
            )

        import backend.services.scan_service as scanner
        assert scanner._scan_registered_storage(1, location_id)["imported"] == 1
        (source_root / "keep.bin").unlink()
        source_root.rmdir()

        with pytest.raises(FileNotFoundError):
            scanner._scan_registered_storage(1, location_id)
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute(
                "SELECT is_deleted FROM assets WHERE filename='keep.bin'"
            ).fetchone()[0] == 0


def test_background_scanner_allows_only_one_scan_per_user(tmp_path, monkeypatch):
    client, root = build_client(tmp_path)
    source_root = tmp_path / "ConcurrentSource"
    source_root.mkdir()
    location_id = str(uuid4())
    entered = threading.Event()
    release = threading.Event()
    with client:
        login(client)
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO storage_locations(id,user_id,name,path,is_default,created_at,updated_at) "
                "VALUES(?,1,'Concurrent',?,0,'2026-01-01','2026-01-01')",
                (location_id, str(source_root)),
            )

        import backend.services.scan_service as scanner

        def blocked_scan(_user_id, _location_id):
            entered.set()
            release.wait(2)
            return {"imported": 0, "updated": 0, "deleted": 0, "skipped_existing": 0, "errors": []}

        monkeypatch.setattr(scanner, "_scan_registered_storage", blocked_scan)
        first = scanner.start_background_scan(1, location_id)
        assert first["scan_started"] is True and entered.wait(1)
        second = scanner.start_background_scan(1, location_id)
        assert second["scan_started"] is False
        assert second["message"] == "A storage scan is already running"
        release.set()
        deadline = time.monotonic() + 2
        while 1 in scanner._running_scans and time.monotonic() < deadline:
            time.sleep(0.01)
        assert 1 not in scanner._running_scans
