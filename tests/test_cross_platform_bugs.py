"""Cross-platform regression tests for Windows, Linux, and macOS behavior."""

import os
import platform
import tempfile
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

import pytest

class TestCrossPlatformBugConditions:
    """Regression coverage for the original platform-specific failures."""

    def test_bug_1_config_initialization_fails_on_linux(self, tmp_path):
        """
        Unix defaults use the user's home while Windows keeps E:\\MyNAS.
        """
        from backend import config as config_module

        unix_home = Path("/home/mynas-test")
        with patch.object(config_module.platform, 'system', return_value='Linux'):
            with patch.object(config_module.Path, 'home', return_value=unix_home):
                with patch.dict(os.environ, {'MYNAS_ROOT': ''}, clear=False):
                    assert config_module._resolve_data_root() == unix_home / "MyNAS"

        with patch.object(config_module.platform, 'system', return_value='Windows'):
            with patch.dict(os.environ, {'MYNAS_ROOT': ''}, clear=False):
                assert config_module._resolve_data_root() == Path(r"E:\MyNAS")

        configured = tmp_path / "ConfiguredRoot"
        with patch.dict(os.environ, {'MYNAS_ROOT': str(configured)}, clear=False):
            assert config_module._resolve_data_root() == configured

    def test_bug_2_path_validation_rejects_unix_paths_on_linux(self):
        """
        Test that validate_storage_path rejects valid Unix paths on Linux

        Bug: Regex only matches Windows drive letters, rejects /mnt/storage
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        from backend.services.settings_service import validate_storage_path

        with patch('platform.system', return_value='Linux'):
            # On Linux, these paths should be valid
            unix_paths = [
                "/mnt/storage",
                "/home/user/nas",
                "/var/lib/mynas",
            ]

            for unix_path in unix_paths:
                try:
                    # This will FAIL on unfixed code - raises ValueError
                    result = validate_storage_path(unix_path)
                    # Expected: Should accept Unix absolute paths on Linux
                    assert result == unix_path, f"Path validation altered path: {result}"
                except ValueError as e:
                    # Bug confirmed: Rejects valid Unix paths
                    pytest.fail(
                        f"Bug confirmed: validate_storage_path rejects valid Unix path '{unix_path}' "
                        f"with error: {e}"
                    )

    def test_windows_drive_paths_remain_supported(self):
        from backend.services.settings_service import validate_storage_path

        assert validate_storage_path(r"F:\Photos") == r"F:\Photos"

    def test_bug_3_path_validation_rejects_macos_paths(self):
        """
        Test that validate_storage_path rejects valid macOS paths

        Bug: Regex only matches Windows drive letters, rejects /Users/admin/nas
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        from backend.services.settings_service import validate_storage_path

        with patch('platform.system', return_value='Darwin'):
            # On macOS, these paths should be valid
            macos_paths = [
                "/Users/admin/nas",
                "/Volumes/Data",
                "/Library/Application Support/MyNAS",
            ]

            for macos_path in macos_paths:
                try:
                    # This will FAIL on unfixed code - raises ValueError
                    result = validate_storage_path(macos_path)
                    # Expected: Should accept Unix absolute paths on macOS
                    assert result == macos_path, f"Path validation altered path: {result}"
                except ValueError as e:
                    # Bug confirmed: Rejects valid macOS paths
                    pytest.fail(
                        f"Bug confirmed: validate_storage_path rejects valid macOS path '{macos_path}' "
                        f"with error: {e}"
                    )

    @pytest.mark.parametrize("unsafe_path", [
        "relative/photos", "../photos", "/", "/etc/mynas", "/bin/tools", "/System/Library/MyNAS",
    ])
    def test_storage_path_rejects_relative_traversal_and_sensitive_roots(self, unsafe_path):
        from backend.services.settings_service import validate_storage_path

        with pytest.raises(ValueError):
            validate_storage_path(unsafe_path)

    def test_bug_4_uuid_collision_on_case_sensitive_filesystem(self):
        """
        Test that scanner generates identical UUIDs for files differing only in case

        Bug: Uses .lower() on relative path before UUID generation
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        from backend.services import scan_service

        namespace = UUID('12345678-1234-5678-1234-567812345678')

        # Files that differ only in case
        file1 = "photo.jpg"
        file2 = "Photo.jpg"

        with patch.object(scan_service.platform, 'system', return_value='Linux'):
            assert scan_service._scanner_asset_id(namespace, file1) != scan_service._scanner_asset_id(namespace, file2)

        with patch.object(scan_service.platform, 'system', return_value='Windows'):
            assert scan_service._scanner_asset_id(namespace, file1) == scan_service._scanner_asset_id(namespace, file2)

        with patch.object(scan_service.platform, 'system', return_value='Darwin'):
            assert scan_service._scanner_asset_id(namespace, file1) != scan_service._scanner_asset_id(namespace, file2)

    def test_bug_5_dashboard_returns_wrong_device_name_on_linux(self):
        """
        Test that dashboard returns "Windows NAS" instead of hostname on Linux

        Bug: Uses COMPUTERNAME env var which doesn't exist on Unix
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        # Directly check the code logic in system_service.py
        # The bug is: os.environ.get("COMPUTERNAME", "Windows NAS")
        # This doesn't use platform detection

        import inspect
        from backend.services import system_service

        source = inspect.getsource(system_service.dashboard)

        # Bug: Uses COMPUTERNAME without platform detection
        if 'COMPUTERNAME' in source and 'platform.system' not in source:
            # On Linux/macOS without COMPUTERNAME, it returns "Windows NAS"
            # Expected: Should use socket.gethostname() on Unix systems
            pytest.fail(
                f"Bug confirmed: dashboard() uses COMPUTERNAME without platform detection\n"
                f"  On Linux/macOS, COMPUTERNAME doesn't exist and falls back to 'Windows NAS'\n"
                f"  Expected: Should use socket.gethostname() on Unix systems"
            )

    def test_bug_6_upload_security_allows_unix_executables(self):
        """
        Test that upload security allows Unix/macOS executables

        Bug: BLOCKED_EXTENSIONS only contains Windows executables
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        from backend.core.security import BLOCKED_EXTENSIONS, validate_upload

        # Unix executable extensions that should be blocked
        unix_executables = ['.sh', '.bin', '.run', '.AppImage', '.deb', '.rpm']

        # macOS executable extensions that should be blocked
        macos_executables = ['.app', '.dmg', '.pkg', '.command']

        # Check current blocklist
        missing_unix = [ext for ext in unix_executables if ext.lower() not in BLOCKED_EXTENSIONS]
        missing_macos = [ext for ext in macos_executables if ext.lower() not in BLOCKED_EXTENSIONS]

        # Bug confirmed if any Unix/macOS executables are not blocked
        if missing_unix or missing_macos:
            pytest.fail(
                f"Bug confirmed: Upload security missing platform-specific executables\n"
                f"  Missing Unix executables: {missing_unix}\n"
                f"  Missing macOS executables: {missing_macos}\n"
                f"  Current blocklist: {sorted(BLOCKED_EXTENSIONS)}"
            )

    def test_bug_7_file_creation_time_uses_wrong_stat_on_linux(self):
        """
        Test that file creation time uses st_ctime incorrectly on Linux

        Bug: st_ctime is metadata change time on Unix, not creation time
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        # On Linux, st_ctime != creation time
        # st_ctime = metadata change time (inode change time)
        # st_birthtime = creation time (only on macOS/BSD)
        # st_mtime = modification time

        with patch('platform.system', return_value='Linux'):
            # Create a temporary file to inspect stat semantics
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(b"test content")

            try:
                stat = tmp_path.stat()

                # On Linux, st_ctime is NOT creation time
                # The bug is that asset_service.py uses st_ctime universally

                # Check if code is using st_ctime (the bug)
                from backend.services import asset_service
                import inspect

                source = inspect.getsource(asset_service.create_file_asset)

                assert 'st_ctime' not in source
                assert 'utc_now()' in source

            finally:
                tmp_path.unlink(missing_ok=True)

    def test_bug_8_missing_unix_startup_script(self):
        """
        Test that no start.sh script exists for Unix systems

        Bug: Only start.ps1 (PowerShell) exists
        Expected to FAIL on unfixed code (confirms bug exists)
        """
        # Check for Unix startup script
        project_root = Path(__file__).parent.parent
        start_sh = project_root / "start.sh"

        # Bug: start.sh doesn't exist
        if not start_sh.exists():
            pytest.fail(
                f"Bug confirmed: No Unix startup script found\n"
                f"  Expected: {start_sh}\n"
                f"  Only PowerShell script (start.ps1) is available\n"
                f"  Unix users must install PowerShell Core or manually start the app"
            )

        # Expected: start.sh should exist and be executable
        assert start_sh.is_file(), "start.sh should be a file"

        # On Unix, check if executable
        if platform.system() != 'Windows':
            stat = start_sh.stat()
            is_executable = bool(stat.st_mode & 0o111)
            assert is_executable, "start.sh should have executable permissions"
