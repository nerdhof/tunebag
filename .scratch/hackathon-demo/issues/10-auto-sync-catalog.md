# 10: Auto-sync catalog between paired peers

**What to build:** When a trusted peer is reachable, catalog events sync without the listener pressing Sync. Local catalog writes also trigger a sync attempt. The Sync button remains as a manual override.

**Blocked by:** 01: Pair two devices

**Status:** ready-for-agent

- [ ] A catalog change on one paired device becomes visible on the other while the peer is reachable, without pressing Sync.
- [ ] Becoming reachable again after a gap triggers a sync attempt.
- [ ] The Sync control still forces an immediate sync.
- [ ] Auto-sync uses the same signed event ingest path as manual sync.
