from backend.db.database import connection
from tests.test_api import build_client, login, photos_root, png_bytes


def test_trash_soft_delete_and_restore(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)

        # 1. Upload a file
        upload_resp = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("test.png", png_bytes(), "image/png")}
        )
        asset = upload_resp.json()["uploaded"][0]
        asset_id = asset["id"]

        # 2. Check it exists in normal list
        items = client.get("/api/assets/list", params={"parent_id": root_id}).json()["items"]
        assert any(item["id"] == asset_id for item in items)

        # 3. Soft delete it
        del_resp = client.delete(f"/api/asset/{asset_id}")
        assert del_resp.status_code == 200

        # 4. Check it's gone from normal list
        items = client.get("/api/assets/list", params={"parent_id": root_id}).json()["items"]
        assert not any(item["id"] == asset_id for item in items)

        # 5. Check it exists in trash
        trash_items = client.get("/api/trash").json()["items"]
        assert any(item["id"] == asset_id for item in trash_items)

        # Physical file should still exist
        with connection() as conn:
            path = conn.execute("SELECT storage_path FROM assets WHERE id=?", (asset_id,)).fetchone()[0]
            assert (root / path).exists()

        # 6. Restore it
        res_resp = client.post(f"/api/trash/{asset_id}/restore")
        assert res_resp.status_code == 200

        # 7. Check it exists in normal list again
        items = client.get("/api/assets/list", params={"parent_id": root_id}).json()["items"]
        assert any(item["id"] == asset_id for item in items)
        
        # 8. Check it's gone from trash
        trash_items = client.get("/api/trash").json()["items"]
        assert not any(item["id"] == asset_id for item in trash_items)


def test_trash_permanent_delete_and_empty(tmp_path):
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)

        def custom_png_bytes(color):
            import io
            from PIL import Image
            stream = io.BytesIO()
            Image.new("RGB", (16, 12), color).save(stream, "PNG")
            return stream.getvalue()

        # Upload two files
        asset1 = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("test1.png", custom_png_bytes("#111111"), "image/png")}
        ).json()["uploaded"][0]
        
        asset2 = client.post(
            "/api/upload", data={"parent_id": root_id},
            files={"files": ("test2.png", custom_png_bytes("#222222"), "image/png")}
        ).json()["uploaded"][0]
        
        # Soft delete both
        client.delete(f"/api/asset/{asset1['id']}")
        client.delete(f"/api/asset/{asset2['id']}")
        
        # Permanent delete asset1
        pdel_resp = client.delete(f"/api/trash/{asset1['id']}/permanent")
        assert pdel_resp.status_code == 200
        
        # Verify physical file for asset1 is gone
        # The storage_path is inside root / "Storage" / "1" / asset_id
        # Let's just check the DB to ensure it's removed
        with connection() as conn:
            row1 = conn.execute("SELECT * FROM assets WHERE id=?", (asset1['id'],)).fetchone()
            assert row1 is None
            row2 = conn.execute("SELECT storage_path FROM assets WHERE id=?", (asset2['id'],)).fetchone()
            assert row2 is not None
            assert (root / row2[0]).exists()
            
        # Empty trash (removes asset2)
        empty_resp = client.delete("/api/trash")
        assert empty_resp.status_code == 200
        assert asset2['id'] in empty_resp.json()["deleted_ids"]
        
        # Verify physical file for asset2 is gone
        with connection() as conn:
            row2_after = conn.execute("SELECT * FROM assets WHERE id=?", (asset2['id'],)).fetchone()
            assert row2_after is None
            
        # Trash should be empty
        assert len(client.get("/api/trash").json()["items"]) == 0
