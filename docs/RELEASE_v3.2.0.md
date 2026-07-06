# MyNAS v3.2.0 — Data Consistency Release

MyNAS is a Windows-native personal cloud for people who want to manage private photos and files remotely without replacing Windows, installing a second operating system, or moving their data into a third-party cloud.

Version 3.2.0 is a correctness-focused release. It does not redesign the application or add a new platform layer. Instead, it makes scanning, backup, search, and sorting behave consistently as the library changes over time.

## What changed

- Registered Storage scans now reconcile new, modified, and deleted source files.
- Repeated registered and legacy scans are idempotent and do not create duplicate Assets.
- Modified files are copied through a verified staging file before the managed copy is replaced.
- An unavailable Storage Location cannot trigger a mass soft-delete.
- Backup payloads now honor the configured external destination instead of internal UUID storage.
- Backup snapshots are SHA256-verified and atomically published only after every file succeeds.
- Photo search now queries the complete user-scoped database through `/api/photos/search`.
- The saved photo sorting preference now controls backend result order.
- SQLite connections use WAL with an explicit busy timeout for concurrent scanner and upload work.

## Compatibility

- No Asset schema change.
- No API was removed.
- Existing JWT and HttpOnly-cookie authentication is unchanged.
- The upload validation pipeline is unchanged and remains separate from trusted scanning.
- Existing v3.1 data is migrated through normal scanner reconciliation; no manual database migration is required.

## Verification

- 44 backend tests passed.
- Vue 3 production build passed.
- Python compilation passed.
- Production FastAPI health probe returned `200 {"status":"ok"}`.
- Login-page browser smoke test completed without console errors.

## Upgrade notes

1. Stop the existing MyNAS process.
2. Replace the application source with v3.2.0.
3. Install dependencies from `requirements.txt` and run `npm ci` if needed.
4. Run `npm run build`.
5. Configure a backup directory outside `MYNAS_ROOT` before running a backup.
6. Start FastAPI and allow the first scanner reconciliation to complete.

## Known boundary

MyNAS verifies that the backup destination is outside the MyNAS data tree. A different Windows path or volume does not, by itself, prove that the destination is a separate physical disk. Important data should still have an additional offline or off-site copy.
