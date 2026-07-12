import json
import re
import time
from pathlib import Path

from PIL import Image

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


def test_pwa_assets_are_installable_and_exclude_api_cache(tmp_path):
    dist = Path(__file__).resolve().parent.parent / "dist"
    manifest_path = dist / "manifest.webmanifest"
    service_worker_path = dist / "sw.js"
    if not manifest_path.is_file() or not service_worker_path.is_file():
        import pytest
        pytest.skip("PWA assets require npm run build")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "MyNAS 管理中心"
    assert manifest["short_name"] == "MyNAS"
    assert manifest["lang"] == "zh-CN"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["theme_color"] == "#4b68f4"
    assert {item["sizes"] for item in manifest["icons"]} == {"192x192", "512x512"}

    for filename, expected_size in (
        ("pwa-192x192.png", (192, 192)),
        ("pwa-512x512.png", (512, 512)),
        ("apple-touch-icon.png", (180, 180)),
    ):
        with Image.open(dist / filename) as icon:
            assert icon.size == expected_size
            assert icon.mode == "RGB"

    worker_source = service_worker_path.read_text(encoding="utf-8")
    precached_urls = re.findall(r'url:\s*["\']([^"\']+)', worker_source)
    assert precached_urls
    assert all(not url.lstrip("/").startswith("api/") for url in precached_urls)

    client, _ = build_client(tmp_path)
    with client:
        responses = {
            "/manifest.webmanifest": "application/manifest+json",
            "/sw.js": "application/javascript",
            "/pwa-192x192.png": "image/png",
            "/pwa-512x512.png": "image/png",
            "/apple-touch-icon.png": "image/png",
        }
        for path, content_type in responses.items():
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(content_type)
        assert client.get("/api/auth/me").status_code == 401
