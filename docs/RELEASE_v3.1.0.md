# MyNAS v3.1.0 — Windows Personal Cloud

MyNAS v3.1.0 turns a Windows PC into a private, photo-first personal cloud. It combines an iCloud Photos-style library and timeline with secure Asset-based file access, configurable Windows storage, incremental backup, and a bilingual interface—all in a compact FastAPI, Vue 3, and SQLite application.

## Release highlights

- Photo library, EXIF-aware timeline, recent uploads, favorites, and full-screen preview.
- Secure UUID file storage with per-user Asset ownership and path isolation.
- Database-backed Storage Locations with automatic background indexing.
- Drag-and-drop multi-file upload with progress and localized feedback.
- Dashboard metrics, recent activity, storage usage, backup state, and system health.
- Settings Center covering account, session, language, storage, backup, and preferences.
- Incremental SHA-256 backup with manual and scheduled execution.
- Simplified Chinese and English translation dictionaries.
- Audit logging for authentication, file, Storage, scanner, and backup actions.

## Architecture

MyNAS is a Windows-native monolith by design: Vue 3 provides the browser interface, FastAPI owns authenticated APIs and service logic, SQLite stores users and Assets, and managed bytes use backend-generated UUID paths. `Asset` remains the only source of truth presented to the UI.

Uploads and filesystem scans have separate trust boundaries. Uploads validate untrusted browser content; the trusted scanner recursively indexes registered Windows directories and creates Assets without weakening upload security.

## Security

- JWT authentication with HttpOnly cookie support.
- Deny-by-default API access outside login.
- Per-user Asset and Storage Location ownership checks.
- No path-based download, delete, preview, or thumbnail API.
- MIME, extension, signature, and size validation for uploads.
- Parameterized SQLite queries and audited sensitive actions.
- Localhost binding by default with HTTPS guidance for remote access.

## Validation

- Backend automated suite: 32 passed.
- Python bytecode compilation: passed.
- Vue production build: passed.
- Production SPA routes: passed.
- Storage registration and scan integration: passed.
- Photos, Timeline, Dashboard, and Settings runtime checks: passed.
- Browser console errors in verified flows: none.

## Installation

See the [README](../README.md) for Windows prerequisites, quick start, production-style build instructions, environment variables, and Cloudflare guidance.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Settings](SETTINGS.md)
- [Storage Locations](STORAGE.md)
- [Scan System](SCAN_SYSTEM.md)
- [Security](SECURITY.md)
- [Changelog](../CHANGELOG.md)
