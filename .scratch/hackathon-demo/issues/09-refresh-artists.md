# 09: Refresh artists in the shared catalog

**What to build:** The listener re-lists known artists' own uploads. New mixes become catalog rows; existing platform ids and committed rejects are left alone. No audio is downloaded. Peers see the new rows after sync.

**Blocked by:** 02: Add artists to the shared catalog

**Status:** ready-for-human

- [x] One artist or all catalog artists can be refreshed in one step.
- [x] Refresh reuses the same source `list_uploads` path as add.
- [x] Uploads whose platform id is already in the catalog are skipped.
- [x] Committed rejects are not resurrected as new catalog rows.
- [x] The same min-duration default (20 minutes) and per-call override apply.
- [x] Refresh creates no audio files.
- [x] New rows appear on the paired device after sync.

## Comments

- Implemented `DeviceAgent.refresh_artists` (optional `artist_ids`, else all catalog artists). Skips known `(platform, platform_id)` including rejected rows. HTTP `POST /api/artists/refresh`; UI per-artist Refresh + Refresh all. Tests in `tests/test_refresh_artists.py`.
