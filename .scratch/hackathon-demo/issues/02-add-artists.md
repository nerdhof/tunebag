# 02: Add artists to the shared catalog

**What to build:** The listener adds several artist URLs and both devices show those artists' own uploads as catalog rows. No audio is downloaded.

**Blocked by:** 01: Pair two devices

**Status:** ready-for-human

- [x] Several artist URLs can be added in one step.
- [x] Each artist contributes only that artist's own uploads.
- [x] Each upload is a catalog row with title, duration, and source URL.
- [x] The rows appear on the paired device after sync.
- [x] Adding artists creates no audio files.
- [x] SoundCloud and hearthis.at URLs are accepted via Source adapters.
- [x] Uploads shorter than a configurable minimum (default 20 minutes) are skipped.

## Comments

- Implemented `DeviceAgent.add_artists` with injected `Source` (FakeSource in tests; CompositeSource SoundCloud+hearthis in serve). Min duration default 1200s. `artists()` / `files()` on the agent seam. HTTP `POST /api/artists` + catalog form. Refresh deferred to issue 09. Tests in `tests/test_add_artists.py` and `tests/test_source_routing.py`.
