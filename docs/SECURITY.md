# Security Architecture

MyNAS v3.1 uses a deny-by-default, Asset-centered security model. The application is designed for a trusted Windows host and does not expose raw filesystem paths as a public file API.

## Authentication

Every valid API except `POST /api/auth/login` requires a JWT. The token may be sent through an HttpOnly, SameSite=Strict cookie or an `Authorization: Bearer` header. Missing, expired, or unknown-user sessions return `401`.

Login attempts are rate-limited by client IP. A default local-development password must be changed after login; shared deployments should set a strong `MYNAS_ADMIN_PASSWORD` before the first start.

## Authorization

Every Asset belongs to a `user_id`. Download, delete, restore, thumbnail, favorite, tag, backup, and listing operations resolve the authenticated user and verify Asset ownership. Cross-user access returns `403`.

Storage Location records are also user-owned. Their paths are configuration data for the trusted scanner, not download paths.

## Asset and path boundary

Managed files are stored under:

```text
<MYNAS_ROOT>\Storage\<user_id>\<asset_uuid>
```

The backend generates the UUID filename. The original filename is display metadata and never participates in managed path construction. Before reading or deleting bytes, MyNAS resolves the database path and verifies that it remains inside the authenticated user's storage root.

Public Asset responses use an explicit allowlist and exclude `storage_path` and thumbnail disk paths.

## Upload security

The upload pipeline handles untrusted browser content and enforces:

- Allowed MIME type and extension combinations.
- JPEG, PNG, MP4, and PDF file signatures.
- Explicit executable and script-extension rejection.
- Maximum upload size while streaming.
- Backend-generated UUID storage names.
- SHA-256 calculation after writing.
- One Asset per uploaded file; identical bytes may use a hard link when the filesystem supports it.
- Full cleanup of Asset, thumbnail, and managed file if the operation fails.

## Scanner security

The scanner is a separate trusted ingestion system. It does not call upload validation or apply the upload allowlist. It reads only a registered, user-owned Storage Location from SQLite, recursively indexes files, and copies managed bytes into the same UUID boundary.

Scanner-created Assets use the same ownership and public-serialization rules as uploaded Assets. See [Scan System](SCAN_SYSTEM.md).

## Database safety

SQLite queries use bound parameters. Asset IDs and Storage Location IDs are UUIDs at API boundaries. Schema initialization and additive migrations run at startup.

## Audit trail

Audit records cover login success and failure, logout, upload, download, delete, restore, permanent deletion, favorites, tags, Storage changes, scans, backups, and scheduling. Records include user, Asset where applicable, client IP, UTC timestamp, and detail text.

## Deployment guidance

- Bind Uvicorn to `127.0.0.1` unless LAN exposure is intentional.
- Use HTTPS for remote access and set `MYNAS_COOKIE_SECURE=true`.
- Keep `Config\jwt-secret.key`, `Config\mynas.db`, backup data, and Cloudflare credentials out of source control.
- Protect the Windows account and volumes hosting MyNAS.
- Treat Storage Location registration as privileged local-host configuration.
- Back up the database and managed storage together.

## Intentionally absent

- No path-based download or preview endpoint.
- No automatic Cloudflare login, tunnel creation, or DNS mutation.
- No Redis, queue, message broker, or remote worker.
- No browser access to backend storage paths.
