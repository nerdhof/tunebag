# 01: Notice bus + coalesce on Catalog/Cache changes

**What to build:** After a local Catalog write or Cache file change on this Device, the agent emits coalesced typed UI notices for the affected sections (`mixes`, `play_history`, `intents`, `peers`, `cache`). An intent rebuild or other multi-Event burst produces at most one notice per section. Tests can subscribe and drain notices through DeviceAgent without a browser.

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] Local Mix add / rate / tag / reject-commit / playhead-style Catalog writes emit the mapped sections (`mixes` and `play_history` where applicable), coalesced per burst.
- [x] Intent create/edit (upsert + Sequence + Assignments) emits a single coalesced `intents` notice for that burst.
- [x] Cache file add/remove emits `cache`.
- [x] Device pair/unpair (and pair-candidate set changes that the agent already tracks) emit `peers`.
- [x] Subscribers can observe the same coalesced notices via a DeviceAgent-facing subscribe/drain API.
- [x] Agent tests cover the above without SSE or browser.

## Comments

- Implemented `ViewNoticeBus` (`ui_notices.py`) with nested batch coalesce; DeviceAgent maps Catalog Events → sections, marks `cache` on store/remove, and `peers` on pair-candidate set changes. Public API: `drain_view_notices` / `subscribe_view_notices`. Tests in `tests/test_notice_bus_coalesce.py`. Peer ingest notices are issue 02; SSE/UI is issue 03.
