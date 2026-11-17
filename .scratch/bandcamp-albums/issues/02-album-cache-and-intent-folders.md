# 02: Album Cache fill + intent folders

**What to build:** Assigned Album Releases fill by downloading each track into one cache directory for that Release. An Album counts as present only when every track is local. Intent folders expose each Album as a subfolder of ordered track files. Peer copy is all-or-nothing for the Album.

**Blocked by:** 01: Album Releases in Catalog (FakeSource)

**Status:** ready-for-human

- [x] Cache fill fetches per-track bytes for an Album (via FakeSource) into one directory keyed by the Release.
- [x] An Album is not present in Cache until all tracks are local; incomplete directories do not satisfy “has file.”
- [x] Failed/partial fills leave the Album absent (and do not strand a “present” half-disc).
- [x] Intent folders place Mixes as single files and Albums as subfolders of ordered track files.
- [x] Peer file copy for an Album transfers the whole track set or leaves the Album absent.
- [x] Metered / assignment fill treats an Album Release like any other assigned Release (no special Bandcamp policy).

## Comments

- Implemented Album cache as `blobs/<release_id>/` with ordered track files; presence requires every Catalog track. Origin fill fetches each track URL; peer handoff via `album_track_bytes` (all-or-nothing). Intent folders: Mix = file, Album = subfolder. Tests in `tests/test_album_cache_and_intent_folders.py`.
