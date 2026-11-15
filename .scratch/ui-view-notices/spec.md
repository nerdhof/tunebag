Status: ready-for-agent

# UI view notices (Agent → browser freshness)

## Problem Statement

Catalog and Cache already update on a Device when the listener writes locally or when a Peer’s Event log is ingested (including auto-sync). The browser UI on that Device often stays stale until something forces a refetch (Sync, Rejected filter, another local action). Listeners think sync failed when the agent already has the new Artists, Mixes, Intents, Assignments, Play history, Peers, or cached files.

## Solution

Keep Device↔Device replication on the Event log. On each Device, after Catalog apply/ingest or Cache file mutations, the agent emits coalesced, typed **UI notices** over SSE. Every open browser on that Device refetches only the affected surfaces (`mixes`, `play_history`, `intents`, `peers`, `cache`). On SSE connect/reconnect, the UI does one full refresh of those surfaces. Sync remains a manual Event-log pull + fill override, not the freshness crutch.

## User Stories

1. As a listener, I want a Mix added on a paired Peer to appear in Catalog browse on this Device’s open UI without pressing Sync or toggling filters, so that peer catalog work feels live.
2. As a listener, I want a new Artist that arrived via Event-log ingest to show up in Catalog views without a manual refresh, so that I trust auto-sync happened.
3. As a listener, I want Play history to update when Last heard / play-related Catalog state changes on this Device (local or ingested), so that the history panel matches the agent.
4. As a listener, I want a new or edited Intent on this Device or a Peer to show in the intents list without pressing Sync, so that planning stays shared on screen.
5. As a listener, I want Sequence and Assignment changes (including device hours / allocations) to refresh the intents UI after they apply, so that budgets and prefixes match Catalog.
6. As a listener, I want trusted Peer list changes (pair, unpair, ingest of pairing-related Catalog state) to refresh the peers panel, so that trust state is visible.
7. As a listener, I want pair candidates from discovery to refresh under the same peers refresh path, so that I do not need a separate poll to see who I can pair.
8. As a listener, I want Cache file add/remove to update cached-audio counts and file-related UI without pressing Fill or Sync, so that fill progress is visible at the list level.
9. As a listener, I want rating a Mix to refresh mixes and Play history panels on every open tab for this Device, so that stars match Catalog.
10. As a listener, I want tagging a Mix to refresh mixes and Play history without a full page reload, so that tags show everywhere on this Device.
11. As a listener, I want a committed Reject or Un-reject to refresh mixes and Play history, so that Rejected filter views stay correct after the undo window commits.
12. As a listener, I want Playhead Catalog updates to refresh mixes and Play history without spamming a notice on every seek tick coalesced away, so that resume state is eventually visible without melting the UI.
13. As a listener, I want creating one Intent (upsert + Sequence + Assignments) to cause a single coalesced `intents` notice, not one refresh per Event, so that the list does not flicker.
14. As a listener, I want a full Event-log pull that applies many Events to produce at most one coalesced notice per affected section, so that catch-up sync does not N-refresh the page.
15. As a listener with two browser tabs on the same Device, I want both tabs to receive the same notices after a local write or peer ingest, so that every attached UI converges.
16. As a listener whose SSE connection dropped, I want reconnect to trigger one full refresh of mixes, Play history, intents, peers, and cache, so that I do not miss notices while offline.
17. As a listener opening the UI for the first time, I want the initial SSE connect to drive that same full five-surface refresh (or equivalent), so that cold load is consistent with reconnect.
18. As a listener, I want Sync to still pull Peers’ Event logs and request fill, so that I retain a manual override when auto-sync or meet fails.
19. As a listener, I want Sync to no longer be required just to see already-applied Catalog or Cache state, so that Sync is not a fake “reload UI” button.
20. As a listener, I do not want Activity feed lines to require this notice system in this pass, so that operational chat stays on its existing poll.
21. As a listener, I do not want Metered toggle, Reject undo countdown, player transport (play/pause/seek while playing), or fill-in-progress chrome to be driven by UI notices in this pass, so that high-churn local chrome stays out of the design.
22. As a listener, I want notices to stay on this Device only (not replicated in the Event log), so that UI plumbing does not become a second Catalog sync channel.
23. As a listener, I want the browser to keep mutating via existing HTTP APIs, so that SSE is observe-only.
24. As an agent author, I want tests to assert notices through DeviceAgent after local writes and peer ingest, so that AFK work does not depend on a real browser.
25. As an agent author, I want a thin HTTP SSE test only for subscribe/connect shape if needed, so that transport stays a detail over the agent seam.

## Implementation Decisions

- Sole behavioral seam remains DeviceAgent. HTTP SSE is transport to that agent; the browser refetches existing read APIs when notices arrive.
- Do not stream Event-log entries to the browser. Notices are Device-local signals that a named UI section’s backing state changed.
- Notice section taxonomy (typed channels, not new CONTEXT glossary nouns): `mixes`, `play_history`, `intents`, `peers`, `cache`.
- Catalog Event apply/ingest mapping (conceptual): Mix/Artist/tag/rating/reject-commit/playhead/played/last-heard-class changes → `mixes` and, when Play history is affected, also `play_history`. Intent upsert/delete, Sequence, Assignment → `intents`. Device paired/unpaired and pair-candidate set changes → `peers`. File bytes appearing or disappearing in Cache → `cache`.
- Playhead, rating, tag, and reject-commit never invent per-tick or per-keystroke channels; they collapse to `mixes` + `play_history` with coalescing.
- Pair candidates fold into `peers` (no separate `pairing` channel).
- Coalesce per section across a short window and/or until end of an apply batch / sync pass so intent rebuild and full-log ingest emit at most one notice per affected section per burst.
- All SSE subscribers on this Device receive the same coalesced notices (local write and remote ingest both notify).
- On SSE connect and reconnect, the UI performs one full refresh of mixes, Play history, intents, peers, and cache (no revision counter required in v1).
- Transport is SSE (server → browser). Mutations remain existing HTTP POST/PUT APIs.
- Sync button semantics unchanged: Event-log pull + fill request; UI refresh on Sync may remain as harmless redundancy.
- No `CONTEXT.md` term for UI notices in this pass; no ADR unless implementation discovers a hard-to-reverse surprise.
- Out-of-scope chrome (Activity, Metered, Reject undo UI, player transport, fill-in-progress) must not gain notice types in this spec’s delivery.
- Prefer extending DeviceAgent with an observable notice/subscribe API that tests can drain; wire SSE to that API without putting coalesce logic in the web layer.

## Testing Decisions

- Good tests drive DeviceAgent the way the listener’s Device behaves and assert which notice sections are emitted (and that bursts coalesce). They do not assert SSE framing, browser DOM, or private helper names.
- Primary module under test: DeviceAgent. Prior art: `tests/test_auto_sync_catalog.py` (local write + peer ingest via `connect` / sync), fill-cache and intent agent tests for Cache and Intent/Assignment mutations.
- Cover at least: local Mix/Intent write → expected sections; peer ingest of Catalog Events → expected sections on the receiving agent; intent rebuild burst → single `intents` coalesce; Cache file store/remove → `cache`; multiple subscribers (or two subscribe handles) both observe the same notice; playhead/rating mapped to `mixes`/`play_history` without one notice per unrelated Event in a batch.
- Optional thin HTTP test: SSE endpoint connects and delivers a notice after an agent mutation (TestClient / ASGI pattern already used under `tests/` for other APIs). Skip browser/Playwright as the AFK gate.
- Do not require live two-process demos for merge-ready; in-process peers suffice for ingest-triggered notices.

## Out of Scope

- Changing Event-log sync, auto-sync nudge, or key-proved meet.
- Streaming or filtering Event-log payloads to the browser.
- WebSocket, revision/ETag view API, or cross-Device UI channels.
- Activity feed, Metered, Reject undo countdown, player transport, fill-in-progress notices.
- New CONTEXT glossary entries or ADRs (unless a later surprise forces one).
- Incremental Event-log cursors, Catalog snapshot cache, or redesign of Sync/Fill semantics.
- Making static UI the primary automated test seam.

## Further Notes

- Grill decisions (2026-11-15/16): Device↔Device = Event log only (A); Agent→UI = typed notices (C); scope = Catalog-backed surfaces + Cache; fine section keys with playhead/rating/tag/reject → mixes+play_history (C); coalesce per section (B); SSE; peers include candidates (B); all tabs notified (A); reconnect = full five-surface refresh (A); no CONTEXT term (A); Sync unchanged (A).
- Symptom that motivated this: artist/catalog rows already on the agent appeared only after toggling the Rejected filter (forced `refreshMixes`), not because sync failed.
- Suggested follow-up tickets (not part of publishing this spec alone): agent notice bus + coalesce; SSE route; `app.js` subscribe + refetch wiring; agent tests; optional HTTP SSE smoke test.
