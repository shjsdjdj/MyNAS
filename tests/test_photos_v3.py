import io
import sqlite3

from PIL import Image

from backend.core.security import hash_password
from tests.test_api import build_client, login, photos_root


def jpeg_bytes(color: str, taken_at: str) -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGB", (64, 40), color)
    exif = Image.Exif()
    exif[36867] = taken_at
    image.save(stream, "JPEG", exif=exif)
    return stream.getvalue()


def upload_photo(client, parent_id: str, name: str, color: str, taken_at: str) -> dict:
    response = client.post(
        "/api/upload",
        data={"parent_id": parent_id},
        files={"files": (name, jpeg_bytes(color, taken_at), "image/jpeg")},
    )
    assert response.status_code == 200
    return response.json()["uploaded"][0]


def test_photo_metadata_thumbnail_and_no_path_leak(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        asset = upload_photo(client, photos_root(client), "summer.jpg", "#ef8c3f", "2024:08:17 09:30:15")
        page = client.get("/api/photos", params={"page": 1, "page_size": 10}).json()
        photo = next(item for item in page["items"] if item["id"] == asset["id"])
        assert photo["exif_datetime"] == "2024-08-17T09:30:15"
        assert (photo["width"], photo["height"]) == (64, 40)
        assert photo["thumbnail_url"] == f"/api/assets/{asset['id']}/thumbnail"
        assert "storage_path" not in str(photo)
        assert client.get(photo["thumbnail_url"]).status_code == 200
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(assets)")}
        assert {"exif_datetime", "width", "height", "thumbnail_url", "is_favorite"} <= columns


def test_photo_pagination_timeline_exif_and_recent_order(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        parent = photos_root(client)
        first = upload_photo(client, parent, "older.jpg", "#4b68f4", "2020:01:02 10:00:00")
        second = upload_photo(client, parent, "newer.jpg", "#25abc0", "2025:06:03 12:00:00")
        page1 = client.get("/api/photos", params={"page": 1, "page_size": 1}).json()
        page2 = client.get("/api/photos", params={"page": 2, "page_size": 1}).json()
        assert page1["total"] == 2 and page1["has_more"] is True
        assert page2["has_more"] is False
        assert page1["items"][0]["id"] == second["id"]
        assert page2["items"][0]["id"] == first["id"]
        timeline = client.get("/api/photos/timeline", params={"page_size": 10}).json()
        assert [group["date"] for group in timeline["groups"]] == ["2025-06-03", "2020-01-02"]
        recent = client.get("/api/photos/recent", params={"page_size": 10}).json()
        assert recent["items"][0]["id"] == second["id"]


def test_favorite_toggle_listing_and_ownership(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        asset = upload_photo(client, photos_root(client), "favorite.jpg", "#a35bd8", "2023:04:05 06:07:08")
        toggled = client.patch(f"/api/assets/{asset['id']}/favorite", json={"is_favorite": True})
        assert toggled.status_code == 200 and toggled.json()["is_favorite"] is True
        favorites = client.get("/api/photos/favorites").json()
        assert [item["id"] for item in favorites["items"]] == [asset["id"]]

        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            db.execute(
                "INSERT INTO users(username,password_hash,is_admin,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("photo-viewer", hash_password("PhotoPass123"), 0, "2026-01-01", "2026-01-01"),
            )
            db.commit()
        login(client, "photo-viewer", "PhotoPass123")
        assert client.patch(f"/api/asset/{asset['id']}/favorite", json={"is_favorite": False}).status_code == 403
        assert client.get(f"/api/asset/{asset['id']}/thumbnail").status_code == 403


def test_multi_upload_duplicate_keeps_one_asset_per_file(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        parent = photos_root(client)
        content = jpeg_bytes("#4b68f4", "2024:01:02 03:04:05")
        response = client.post(
            "/api/upload",
            data={"parent_id": parent},
            files=[
                ("files", ("copy-a.jpg", content, "image/jpeg")),
                ("files", ("copy-b.jpg", content, "image/jpeg")),
            ],
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 2
        assert len(payload["assets"]) == 2
        assert len({item["id"] for item in payload["assets"]}) == 2
        assert len(payload["uploaded"]) == 1
        assert len(payload["duplicates"]) == 1
        assert payload["assets"][0]["hash"] == payload["assets"][1]["hash"]

        listing = client.get("/api/assets", params={"parent_id": parent}).json()["items"]
        listed_ids = {item["id"] for item in listing}
        assert listed_ids == {item["id"] for item in payload["assets"]}
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            rows = db.execute(
                "SELECT id,storage_path,thumbnail_storage_path FROM assets WHERE parent_id=? AND type='image'",
                (parent,),
            ).fetchall()
        assert len(rows) == 2
        assert len({row[1] for row in rows}) == 2
        assert all(row[2] for row in rows)
        assert all(client.get(f"/api/assets/{row[0]}/thumbnail").status_code == 200 for row in rows)


def test_plural_asset_api_and_legacy_alias_are_both_secure(tmp_path):
    client, _ = build_client(tmp_path)
    with client:
        login(client)
        asset = upload_photo(client, photos_root(client), "routes.jpg", "#25abc0", "2024:02:03 04:05:06")
        assert client.get(f"/api/assets/{asset['id']}").status_code == 200
        assert client.get(f"/api/asset/{asset['id']}").status_code == 200
        assert client.patch(f"/api/assets/{asset['id']}/favorite", json={"is_favorite": True}).status_code == 200
        assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
        assert client.get(f"/api/assets/{asset['id']}").status_code == 404


def test_corrupt_image_rolls_back_file_asset_and_thumbnail(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        parent = photos_root(client)
        response = client.post(
            "/api/upload",
            data={"parent_id": parent},
            files={"files": ("broken.png", b"\x89PNG\r\n\x1a\nnot-a-real-image", "image/png")},
        )
        assert response.status_code == 400
        with sqlite3.connect(root / "Config" / "mynas.db") as db:
            assert db.execute("SELECT COUNT(*) FROM assets WHERE parent_id=?", (parent,)).fetchone()[0] == 0
        storage_files = [path for path in (root / "Storage" / "1").iterdir() if path.is_file()]
        thumbnail_files = list((root / "Thumbnails" / "1").glob("*.jpg"))
        assert storage_files == []
        assert thumbnail_files == []
