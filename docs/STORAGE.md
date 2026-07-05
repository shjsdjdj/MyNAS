# Storage Locations

Storage Locations connect user-owned Windows directories to the MyNAS Asset index. Each location is stored in SQLite with a UUID, owner, display name, absolute path, default flag, and timestamps.

## Managed storage and registered locations

These concepts are intentionally separate:

- **Managed storage** contains UUID-named file bytes under `MyNAS\Storage\<user_id>\`. All downloads and previews are served from this boundary.
- **Storage Locations** are registered source directories such as `F:\Photos`. They are configuration records used by the trusted scanner.

Registering a location never exposes its real path through a file API. The scanner copies indexed content into managed storage and creates Assets; the UI continues to use only Asset IDs.

## Adding a location

1. Open Settings → Storage.
2. Enter a display name and absolute Windows path.
3. Save the location.
4. If the path is reachable, MyNAS starts a background scan for the current user.
5. Indexed images become available in Photos, Timeline, Recent, and Dashboard.

Example request:

```http
POST /api/settings/storage
Content-Type: application/json

{
  "name": "Photo Archive",
  "path": "F:\\Photos",
  "is_default": false
}
```

The response preserves the existing location fields and adds scan state:

```json
{
  "scan_started": true,
  "scan_required": false,
  "message": "Storage scan started"
}
```

If the drive is unavailable, the record is still created and `scan_required` is `true`. If another scan for the same user is running, MyNAS does not start a concurrent scan.

## Path rules

- Paths must be absolute Windows drive paths.
- Relative paths and `..` traversal are rejected.
- Availability and capacity are read from the server running MyNAS.
- Paths inside the MyNAS data root are handled by the existing internal scanner and are not started as external background scans.
- Paths are always loaded from a user-owned database record before scanning.

## Ownership and access

Storage records are isolated by `user_id`. Updating or deleting another user's record returns `403`. Registering a directory does not create a path-based download endpoint and does not weaken Asset ownership checks.

## Default and deletion behavior

- Every user receives a default Main Storage record.
- Any reachable location may be selected as the default metadata record.
- Set another default before deleting the current default.
- Deleting a location removes only its configuration record.
- Existing Assets and managed UUID files are not deleted with the Storage record.

## Drive availability

External drives and network-mounted drive letters may be offline. MyNAS reports the location as unavailable without removing it. Reconnect the drive before scanning or capacity checks.

For scanner behavior and restart safety, see [Scan System](SCAN_SYSTEM.md).
