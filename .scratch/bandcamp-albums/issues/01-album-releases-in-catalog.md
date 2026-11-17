# 01: Album Releases in Catalog (FakeSource)

**What to build:** Adding a fake Bandcamp-style artist creates **Album** Releases in the Catalog with summed duration/size and ordered track metadata that replicates to a paired Peer. Existing SoundCloud/hearthis uploads remain **Mix** Releases. No audio is downloaded.

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] A FakeSource artist listing can describe full albums (ordered tracks with ids, titles, durations, permalinks).
- [x] `add_artists` ingest creates Album Releases with duration/size equal to the sums of tracks.
- [x] Album track metadata is present on the Catalog Release and appears on a paired Device after sync.
- [x] SoundCloud/hearthis-style single-file uploads still become Mix Releases.
- [x] Adding artists still creates no audio Files.
- [x] Full-album filter applies (≥2 tracks and summed duration ≥ `min_duration_seconds`); smaller releases are skipped.
- [x] Wire/API may still say `mix` / `mix_id`; domain kind distinguishes Mix vs Album.

## Comments

- Implemented via `ReleaseKind` + `AlbumTrack` on Catalog `Mix`, source `Track`/`Upload.tracks`, and `_mix_from_upload` for `add_artists`/`refresh_artists`. Tests in `tests/test_album_releases_in_catalog.py`.
