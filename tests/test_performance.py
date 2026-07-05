import time
from pathlib import Path

from tests.test_api import build_client, login, photos_root, png_bytes
import backend.services.file_service as fs

def test_upload_generates_thumbnail_before_success_response(tmp_path: Path):
    """A successful image upload guarantees its one-to-one thumbnail exists."""
    client, root = build_client(tmp_path)
    with client:
        login(client)
        root_id = photos_root(client)
        
        original_generate = fs.generate_thumbnail
        sleep_time = 0.5
        mock_called = False
        
        def mock_generate_thumbnail(*args, **kwargs):
            nonlocal mock_called
            mock_called = True
            time.sleep(sleep_time)
            return original_generate(*args, **kwargs)
            
        fs.generate_thumbnail = mock_generate_thumbnail
        
        try:
            start_time = time.time()
            response = client.post(
                "/api/upload", data={"parent_id": root_id},
                files={"files": ("timeline.png", png_bytes(), "image/png")},
            )
            elapsed = time.time() - start_time
            
            assert response.status_code == 200
            
            asset = response.json()["assets"][0]
            assert asset["thumbnail_url"] == f"/api/assets/{asset['id']}/thumbnail"
            assert client.get(asset["thumbnail_url"]).status_code == 200
        finally:
            fs.generate_thumbnail = original_generate

def test_static_files_mounted(tmp_path):
    # StaticFiles is only mounted when a built dist/ exists (see backend/main.py).
    # Skip in source-only checkouts where the frontend has not been built.
    if not (Path(__file__).resolve().parent.parent / "dist").is_dir():
        import pytest
        pytest.skip("dist/ not built — static mount is production-build dependent")
    client, root = build_client(tmp_path)
    with client:
        has_static = any(getattr(route, "name", None) == "static" for route in client.app.routes)
        assert has_static, "StaticFiles route 'static' was not mounted"
