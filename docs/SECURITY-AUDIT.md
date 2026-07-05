# MyNAS v3.1 Security Verification

## Release result

- Automated backend suite: **31 passed**.
- Vue/Vite production build: passed.
- Anonymous API route sweep: protected endpoints return `401`.
- Production SPA routes: root, Photos, Timeline, and Settings return the Vue application.
- Registered Storage scan integration: Asset creation, Photos, Timeline, Dashboard, and repeat-scan idempotency passed.

## Requirement mapping

| Requirement | Evidence |
| --- | --- |
| No token means no data access | Route tests cover health, dashboard, Assets, upload, photos, backup, Trash, and Settings. |
| Asset UUID only | Download, delete, thumbnail, favorite, and tag routes use UUID path parameters. |
| User ownership | Cross-user Asset and Storage Location access returns `403`. |
| No request-controlled file paths | Managed file operations derive paths from owned Asset records. |
| No path disclosure | Public Asset serializers omit storage and thumbnail disk paths. |
| Safe upload | Extension, MIME, signature, and size checks run before Asset completion. |
| Scanner/upload isolation | Scanner contains no `validate_upload` call; upload continues to require it. |
| Complete scan indexing | Unknown extensions, executable files, and same-content files at different paths create Assets. |
| Scanner rollback | Simulated Asset creation failure leaves no copied file or incomplete Asset. |
| Registered Storage integration | Adding a reachable location starts a scan and populates Photos, Timeline, and Dashboard. |
| Repeat-scan safety | Stable registered-storage Asset IDs prevent duplicate records. |
| Database-driven UI | Unindexed disk files remain invisible until the scanner creates Assets. |
| SQL injection resistance | Queries are parameterized and injection-style login attempts are rejected. |
| Traceability | Authentication, file, Storage, scan, and backup actions are audited. |
| Incremental backup | Unchanged content is skipped and changed content is copied on the next run. |

## Operational release notes

- Set a strong `MYNAS_ADMIN_PASSWORD` before publishing a remotely reachable instance.
- Use `MYNAS_COOKIE_SECURE=true` only with HTTPS; local HTTP development requires `false`.
- Never commit `MYNAS_ROOT\Config`, user files, backup files, Cloudflare tokens, or generated secrets.
- Cloudflare configuration in this repository is a template and does not create external resources.
