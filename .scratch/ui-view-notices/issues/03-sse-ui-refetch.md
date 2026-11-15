# 03: SSE stream + UI refetch on notices

**What to build:** The browser subscribes to Device UI notices over SSE. On connect/reconnect it fully refreshes mixes, Play history, intents, peers, and cache; afterward it refetches only the panels named by each notice. Multiple tabs on the same Device all stay current. Sync remains manual Event-log pull + fill and is no longer required just to see already-applied Catalog or Cache state.

**Blocked by:** 01: Notice bus + coalesce on Catalog/Cache changes; 02: Notices on Peer Event-log ingest.

**Status:** ready-for-human

- [x] SSE endpoint streams the agent’s coalesced section notices (observe-only; mutations stay on existing HTTP APIs).
- [x] On SSE connect and reconnect, the UI performs one full refresh of mixes, Play history, intents, peers, and cache.
- [x] On `mixes` / `play_history` / `intents` / `peers` / `cache` notices, the matching panels refetch without pressing Sync or toggling filters.
- [x] Two open UIs on the same Device both update after a local write or Peer ingest.
- [x] Sync button semantics unchanged (pull + fill); freshness no longer depends on it when notices work.
- [x] Activity, Metered, Reject undo chrome, player transport, and fill-in-progress are not driven by new notice types.
- [x] Optional thin HTTP SSE smoke test; agent notice tests from 01–02 remain the behavioral gate.

## Comments

- Implemented `GET /api/view-notices` (FastAPI `EventSourceResponse`) subscribed to `DeviceAgent.subscribe_view_notices`; `app.js` `EventSource` does full five-surface refresh on `open` (connect/reconnect) and section refetch on `notice`. Multi-tab fan-out is the existing multi-subscriber bus (01). Tests in `tests/test_sse_ui_refetch.py`.
