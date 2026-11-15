# 03: SSE stream + UI refetch on notices

**What to build:** The browser subscribes to Device UI notices over SSE. On connect/reconnect it fully refreshes mixes, Play history, intents, peers, and cache; afterward it refetches only the panels named by each notice. Multiple tabs on the same Device all stay current. Sync remains manual Event-log pull + fill and is no longer required just to see already-applied Catalog or Cache state.

**Blocked by:** 01: Notice bus + coalesce on Catalog/Cache changes; 02: Notices on Peer Event-log ingest.

**Status:** ready-for-agent

- [ ] SSE endpoint streams the agent’s coalesced section notices (observe-only; mutations stay on existing HTTP APIs).
- [ ] On SSE connect and reconnect, the UI performs one full refresh of mixes, Play history, intents, peers, and cache.
- [ ] On `mixes` / `play_history` / `intents` / `peers` / `cache` notices, the matching panels refetch without pressing Sync or toggling filters.
- [ ] Two open UIs on the same Device both update after a local write or Peer ingest.
- [ ] Sync button semantics unchanged (pull + fill); freshness no longer depends on it when notices work.
- [ ] Activity, Metered, Reject undo chrome, player transport, and fill-in-progress are not driven by new notice types.
- [ ] Optional thin HTTP SSE smoke test; agent notice tests from 01–02 remain the behavioral gate.
