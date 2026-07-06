# Changelog

All notable changes to MyNAS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.

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
