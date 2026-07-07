# Changelog

All notable changes to MyNAS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

## [3.2.5] — 2026-07-07

### Fixed

- Scanner Asset identity now follows host filesystem semantics: Windows paths remain case-insensitive, while Linux and macOS preserve case, including case-sensitive APFS volumes.
- Existing lowercase scanner identities are adopted during reconciliation so upgrades do not create duplicate active Assets.
- Storage path validation accepts absolute Windows, Linux, and macOS paths while rejecting relative paths, traversal, NUL bytes, filesystem roots, and sensitive system directories.
- Asset creation timestamps now use application UTC time instead of platform-dependent filesystem creation-time semantics.
- Dashboard and system information use the real host name instead of a Windows-specific label.
- Upload validation blocks executable and script formats commonly used on Windows, Linux, and macOS without changing the scanner pipeline.

### Added

- Cross-platform data-root defaults: `E:\MyNAS` on Windows and `~/MyNAS` on Linux and macOS, with `MYNAS_ROOT` retaining highest priority.
- Native `start.sh` launcher for Linux and macOS alongside the existing Windows PowerShell launcher.
- Cross-platform regression coverage for configuration, storage validation, scanner identity migration, timestamps, host names, and upload security.

### Changed

- Documentation now describes Windows-first origins and supported Windows, Linux, and macOS deployment paths.
- Version updated to MyNAS 3.2.5 without database-schema, API, authentication, or Asset-model changes.

### Verification

- Backend automated tests: 60 passed.
- Frontend production build: passed with Vite 6.4.2.
- Shell launcher syntax validation: passed.

## [3.2.0] — 2026-07-06

### Fixed

- Registered and legacy scans are idempotent and reconcile new, modified, and deleted source files.
- Scanner file replacement uses verified staging copies and bounded IO retries.
- Backups honor the configured external destination, verify SHA256 integrity, and publish snapshots atomically.
- Photo search uses the database-backed API instead of filtering only loaded browser pages.
- Persisted photo sorting controls the backend Photos, Favorites, and Search result order.
- SQLite connections use an explicit busy timeout for concurrent scanner and upload writes.

## [3.1.1] — 2026-07-06

### Security
- Application-level hardening ahead of public Cloudflare Tunnel release.
- Strict JWT validation: `sub`/`iat`/`exp` required, signature + expiry + issuance verified, configurable clock leeway, per-token `jti`.
- Logout now revokes the active token (fingerprint persisted, auto-pruned after expiry); a logged-out cookie can no longer be reused.
- Authentication is cookie-only for browser clients — the `Authorization: Bearer` fallback has been removed.
- Bounded global rate limiter on every `/api/*` request and the public `/health` probe.
- Request size limit middleware rejects oversized bodies (`413`) before parsing, with a higher ceiling for `/api/upload`.
- Uniform error envelope `{"error":{"code","message"}}` across all handlers; stack traces never reach the client.
- Sensitive path segments (`config`, `storage`, `.db`, `.key`, `.env`, …) are blocked at the SPA fallback boundary.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP `frame-ancestors`, HSTS in production) applied at the edge.
- `MYNAS_ENV=production` now refuses to start with wildcard CORS or insecure cookies.

### Changed
- Public liveness probe `GET /health` returns the minimal `{"status":"ok"}` shape with no internal details.
- `client_ip` trusts forwarding headers only when the peer is listed in `MYNAS_TRUSTED_PROXY_IPS`.
- Cloudflare tunnel template targets the production FastAPI origin `http://127.0.0.1:8000`.

### Compatibility
- No API surface removed. Clients relying on the removed Bearer fallback must send credentials via the `mynas_token` cookie. The authenticated `GET /api/health` is unaffected.

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
