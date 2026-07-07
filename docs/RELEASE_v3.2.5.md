# MyNAS v3.2.5 — Cross-Platform Compatibility Release

MyNAS v3.2.5 keeps the existing FastAPI, Vue 3, SQLite, and Asset-based architecture while removing Windows-only assumptions from backend paths, scanner identity, timestamps, system information, upload security, and startup tooling. Windows behavior remains backward compatible, and no database migration or API change is required.

## Highlights

- Windows-first, cross-platform operation on Windows, Linux, and macOS.
- Host-aware scanner identities that prevent case-collision bugs.
- Restart-safe adoption of legacy lowercase scanner Asset IDs.
- Absolute storage-path validation for drive-letter, POSIX, and macOS volume paths.
- Cross-platform UTC Asset timestamps and real host-name reporting.
- Expanded executable and script upload blocklist without touching scanner behavior.
- Native `start.sh` for Linux and macOS.
- Updated installation, storage, scanner, security, and architecture documentation.

## Fixed bugs

### Scanner path identity

Scanner Asset IDs are still deterministic UUIDs derived from the registered storage location and relative path. Windows normalizes path case because its normal filesystem behavior is case-insensitive. Linux and macOS preserve case so distinct files such as `Photo.jpg` and `photo.jpg` remain distinct on case-sensitive filesystems and APFS volumes.

During the first reconciliation after an upgrade, MyNAS also checks the previous lowercase identity. Matching legacy Assets are adopted instead of duplicated, preserving restart safety and active Asset consistency.

### Storage paths

Storage registration now understands all supported absolute path styles:

- Windows: `E:\Photos`
- Linux: `/mnt/photos`
- macOS: `/Volumes/Photos`

Relative paths, traversal segments, NUL bytes, filesystem roots, and sensitive operating-system directories remain rejected.

### Platform-dependent metadata

New Assets use the application's UTC timestamp rather than filesystem `ctime`, whose meaning differs between operating systems. System information now reports the actual host name instead of a fixed Windows-oriented value.

### Upload safety

The upload pipeline blocks common Windows, Linux, and macOS executable or script extensions. The trusted scanner remains isolated and continues indexing every filesystem entry without upload validation, MIME filtering, or extension filtering.

## Compatibility

- No database schema changes.
- No Asset model changes.
- No API endpoints removed or renamed.
- No authentication changes.
- No new runtime framework or dependency.
- Existing Windows `E:\MyNAS` installations remain compatible.
- `MYNAS_ROOT` continues to override the platform default.

## Verification

- `python -m pytest -p no:cacheprovider -q`: 60 passed.
- `npm run build`: passed; 1,582 modules transformed.
- `sh -n start.sh`: passed.
- `git diff --check`: passed before release.

## Upgrade

Stop MyNAS, replace the application files with v3.2.5, keep the existing data root and configuration, and start the service normally. No migration command is required. The first registered-storage scan performs any needed legacy scanner-ID adoption automatically.
