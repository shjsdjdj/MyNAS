# Security Architecture

MyNAS uses a deny-by-default, Asset-centered security model. The application is designed for a trusted Windows, Linux, or macOS host and does not expose raw filesystem paths as a public file API.

## Authentication

Every API except `POST /api/auth/login` (and the reserved registration path) is denied by a global boundary unless it has a valid JWT in the HttpOnly, SameSite=Strict cookie. Bearer tokens and browser storage are not accepted. Missing, expired, revoked, or unknown-user sessions return `401`.

All API traffic is rate-limited in memory, with a stricter failed-login limiter. Non-upload request bodies are capped separately from streamed uploads. A default local-development password must be changed after login; shared deployments should set a strong `MYNAS_ADMIN_PASSWORD` before the first start.

## Authorization

Every Asset belongs to a `user_id`. Download, delete, restore, thumbnail, favorite, tag, backup, and listing operations resolve the authenticated user and include `user_id` in queries. Cross-user IDs are treated as missing resources.

Storage Location records are also user-owned. Their paths are configuration data for the trusted scanner, not download paths.

## Asset and path boundary

Managed files are stored under:

```text
<MYNAS_ROOT>/Storage/<user_id>/<asset_uuid>
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

Audit records cover security-relevant action types and retain only `user_id`, action, and UTC time. Existing compatibility columns are written with redacted or empty values. Passwords, cookies, tokens, filenames, request details, and IP headers are not persisted.

## Deployment guidance

- Bind Uvicorn to `127.0.0.1` unless LAN exposure is intentional.
- Use HTTPS for remote access and set `MYNAS_COOKIE_SECURE=true`.
- Set `MYNAS_ENV=production`, `MYNAS_PUBLIC_BASE_URL=https://<host>`, and an explicit `MYNAS_CORS_ORIGINS`; production startup rejects wildcard CORS and insecure cookies. `MYNAS_PUBLIC_URL` remains accepted for existing installs.
- Proxy IP headers are ignored unless the immediate proxy IP is explicitly listed in `MYNAS_TRUSTED_PROXY_IPS`.
- Point Cloudflare Tunnel at `http://127.0.0.1:8000` after building the Vue frontend; do not expose the Vite development server.
- Keep `Config\jwt-secret.key`, `Config\mynas.db`, backup data, and Cloudflare credentials out of source control.
- Protect the host account and volumes running MyNAS.
- Treat Storage Location registration as privileged local-host configuration.
- Back up the database and managed storage together.

## Intentionally absent

- No path-based download or preview endpoint.
- No automatic Cloudflare login, tunnel creation, or DNS mutation.
- No Redis, queue, message broker, or remote worker.
- No browser access to backend storage paths.
