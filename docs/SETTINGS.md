# Settings Center

The MyNAS v3.1 Settings Center is available at `/settings` inside the existing Vue shell. Every Settings API requires an authenticated user and stores user-specific data in SQLite.

## Account

- View username and administrator role.
- View JWT issue time, expiry time, and authentication type.
- Change the username with format and uniqueness validation.
- Change the password through the existing authenticated password endpoint.
- Sign out and clear the HttpOnly session cookie.

Changing the username does not change the user's numeric ID or Asset ownership.

## Language

MyNAS supports Simplified Chinese and English. The selected language is stored in browser local storage and in the authenticated user's preferences. Refreshing the page preserves the selection.

The implementation uses the dictionaries in `src/locales/` and does not depend on a heavyweight internationalization framework. See [Internationalization](I18N.md).

## Storage Locations

The Storage card lists user-owned Windows directories with default state, availability, total capacity, usage, and free space. Users can add, rename, delete, and select a default location.

Adding a reachable external directory starts a background scan. An offline path remains saved and the API reports `scan_required: true`. See [Storage](STORAGE.md) and [Scan System](SCAN_SYSTEM.md).

## Backup

- View and change the backup directory.
- Run an incremental backup immediately.
- Enable or disable automatic backup.
- Select the daily execution time.
- View the latest run time and status.

Backup scheduling is persisted in SQLite and restored when the application starts.

## Preferences

- Theme: Light. Dark mode is reserved and disabled in v3.1.
- Default home: Photos, Timeline, Recent, or Overview.
- Default upload directory: a secure root Asset folder.
- Photo ordering: capture time descending, capture time ascending, or upload time descending.

## System information

The System card reports Python, SQLite, and MyNAS versions; database and thumbnail-cache sizes; Asset, photo, video, file, and favorite counts; and managed storage usage.

## API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `PATCH` | `/api/settings/account/username` | Change username |
| `GET`, `PATCH` | `/api/settings/preferences` | Read or update preferences |
| `GET`, `POST` | `/api/settings/storage` | List or add Storage Locations |
| `PATCH`, `DELETE` | `/api/settings/storage/{id}` | Update or remove a location |
| `POST` | `/api/settings/storage/{id}/default` | Select the default location |
| `GET`, `PATCH` | `/api/settings/backup` | Read or update backup settings |
| `POST` | `/api/settings/backup/run` | Run a backup immediately |
| `GET` | `/api/settings/system` | Read system information |

## Operational guidance

- Configure a strong `MYNAS_ADMIN_PASSWORD` before any shared deployment.
- Keep `MYNAS_COOKIE_SECURE=true` behind HTTPS.
- Do not register MyNAS internal storage as an external scan source.
- Set another default Storage Location before deleting the current default record.
