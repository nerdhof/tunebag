# 10: Auto-sync catalog between paired peers

**What to build:** When a trusted peer is reachable, catalog events sync without the listener pressing Sync. Local catalog writes also trigger a sync attempt. The Sync button remains as a manual override.

**Blocked by:** 01: Pair two devices

**Status:** ready-for-human

- [x] A catalog change on one paired device becomes visible on the other while the peer is reachable, without pressing Sync.
- [x] Becoming reachable again after a gap triggers a sync attempt.
- [x] The Sync control still forces an immediate sync.
- [x] Auto-sync uses the same signed event ingest path as manual sync.

## Comments

- Added `request_sync` / `wait_for_sync` (single-flight like fill). Local catalog writes (`_append_and_apply`) and `connect` schedule catalog-only auto-sync and nudge trusted in-process peers to pull; HTTP peers get a best-effort `POST /api/sync`. Manual Sync stays synchronous via `POST /api/sync`. Reject undo window unchanged (pending rejects are not events). Tests in `tests/test_auto_sync_catalog.py`.
