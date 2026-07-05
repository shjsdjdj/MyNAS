# Changelog

All notable changes to MyNAS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

## [3.1.0] — 2026-07-05

### Added

- Complete Settings Center for account, session, language, Storage Locations, backup, system information, and user preferences.
- Lightweight Simplified Chinese and English dictionaries with persisted locale selection.
- Database-backed Windows Storage Locations with CRUD, default selection, capacity, and free-space reporting.
- Automatic background indexing after a reachable Storage Location is registered.
- Restart-safe registered-storage scans using stable per-location Asset identifiers.
- Daily APScheduler backup time, manual backup, last-run state, and configurable backup directory metadata.
- Dashboard resource statistics, recent photos, backup state, recent activity, and system health.
- Drag-and-drop upload, progress feedback, localized toast messages, automatic refresh, and uploaded-photo focus.
- Photo multi-select with batch favorite, download, and delete actions.
- Timeline year and month jump controls.

### Changed

- Version updated to MyNAS 3.1.0.
- All frontend-visible product copy now uses the shared translation dictionary.
- Settings and Security navigation now open the functional Settings Center.
- Scanner and upload behavior are explicitly isolated: trusted scans index all file types while uploads retain strict validation.
- Production static serving now supports direct Vue routes such as `/photos`, `/photos/timeline`, and `/settings`.

### Fixed

- Registering an external Storage Location now populates the Asset database and photo experiences.
- Scanner imports no longer call upload validation or discard same-content files from different paths.
- Scanner failures remove partially copied content and incomplete Asset rows.
- Direct navigation to compiled frontend routes no longer returns `404`.

### Security

- Existing JWT, HttpOnly cookie, Asset ownership, UUID storage, IDOR protection, and path-boundary validation remain unchanged.
- Registered scan paths are loaded from user-owned database records rather than accepted as direct file-operation parameters.
- A per-user running guard prevents concurrent Storage scans.
- Storage Location records cannot bypass Asset-based file access.
