Status: ready-for-agent

# Durable Event log, Identity, and LAN meet

## Problem Statement

Today a listener who kills or restarts Tunebag loses Catalog rows (artists, ratings, intents, pairing). Paired Devices also lose track of each other when IP addresses change across home, work, or hackspace, because reachability was treated like identity. Concurrent edits and clock skew can leave Peers disagreeing about Catalog state even after they sync.

## Solution

Each Device persists its Identity, trusted Peer identities, last-known Locator hints, and the signed Event log. On boot the Catalog is rebuilt by replaying the Event log. Peers meet on the same LAN via mDNS (or a pasted Locator / USB), prove key possession with a challenge–response, then exchange the full Event log. Concurrent events converge with per-type deterministic merge; Playhead uses a hybrid rule. QR or short code is only for establishing trust. Unpair replicates forward-looking trust revocation without rewriting history.

## User Stories

1. As a listener, I want my Device identity (`device_id` + keypair) to survive restart, so that I remain the same Device to my Peers.
2. As a listener, I want trusted Peer identities to survive restart, so that I do not have to pair again after a reboot.
3. As a listener, I want last-known Locator hints to survive restart, so that reconnect can try a previous address without treating that address as Identity.
4. As a listener, I want the Event log to survive restart, so that Catalog history is not lost when the agent process dies.
5. As a listener, I want Artists, Mixes, tags, Stars, Rejects, Played, Intents, Sequences, Assignments, and Playheads to come back after restart, so that planning and taste survive kills.
6. As a listener, I want Catalog after restart to match what replaying the Event log produces, so that disk state cannot silently diverge from the log.
7. As a listener, I want File bytes already on disk to still be there after restart, so that Cache fill is not thrown away.
8. As a listener, I want Metered mode and an in-progress Reject undo timer to stay local and not be required in the Event log, so that ephemeral UI state does not pollute replication.
9. As a listener, I want a Locator (URL/IP) never to grant trust by itself, so that a changed or hostile address cannot impersonate a Peer.
10. As a listener, I want sync to require a challenge–response proving the Peer’s private key, so that advertising someone else’s public key on the LAN cannot steal a meet.
11. As a listener, I want a successful proof to last only for the live meet/session, so that a later process on that address must prove again.
12. As a listener, I want QR or short code only when establishing trust (first pair or re-pair after unpair), so that everyday reconnect does not need a rescan.
13. As a listener, I want re-meeting a still-trusted Peer to use discovery and/or Locator hints plus key proof, so that work→home network changes feel automatic.
14. As a listener, I want my agent to advertise on the LAN via mDNS with name and short code (or key fingerprint), so that other Devices can find a Locator without a pasted URL.
15. As a listener, I want the full public key fetched (pairing payload) before challenge, so that small mDNS records are not treated as authoritative Identity.
16. As a listener, I want browse on agent start, on network/interface change, and with slow periodic refresh when no trusted Peer has a live session, so that network changes are noticed without hammering the LAN.
17. As a listener, I want a discovered advertisement whose public key is already trusted to refresh the Locator hint after proof and then sync, so that paired Devices reunite on a new LAN.
18. As a listener, I want a discovered advertisement whose public key is unknown to appear only as a pair candidate, so that discovery never silently trusts a stranger.
19. As a listener, I want pairing an unknown candidate to still require QR or short code, so that I am not fooled by an adversarial LAN client.
20. As a listener, I want pasted Locator and QR pairing to keep working when mDNS is blocked, so that guest Wi‑Fi still allows a meet.
21. As a listener, I want discovery limited to the same LAN multicast domain, so that we do not pretend cross-network meet works without a relay.
22. As a listener, I want Peers that can reach each other to exchange the full Event log and dedupe by event id, so that both end with the same event set.
23. As a listener, I want Catalog sync to still work on a Metered link, so that taste and plans travel even when audio does not.
24. As a listener, I want auto-sync when a trusted Peer is in a proven live session, so that I do not have to press Sync after every change.
25. As a listener, I want the Sync control to force an immediate sync, so that I can override when needed.
26. As a listener, I want events whose author Device is not yet known to be buffered until that Device is paired into the Catalog, so that partial sync does not silently drop rows.
27. As a listener, I want Artist add and Mix add to be idempotent upserts by id, so that replaying or reordering those events does not duplicate rows.
28. As a listener, I want Artist delete to be sticky, so that a delete is not undone by an older add when events merge.
29. As a listener, I want Stars for a Mix to resolve by last-by signed author time then `(device_id, seq, event.id)`, so that concurrent ratings converge without NTP.
30. As a listener, I want Tags (full list replace) to resolve by last-by signed author time then `(device_id, seq, event.id)`, so that the UI’s full tag list stays deterministic across Peers.
31. As a listener, I want Reject and Played to be sticky once true, so that finishing or rejecting on one Device cannot be undone by an older event from another.
32. As a listener, I want Intent upsert/delete to resolve by last-by signed author time then `(device_id, seq, event.id)`, with delete beating an older upsert, so that plan edits converge.
33. As a listener, I want Sequence and Assignment events to resolve by last-by signed author time then `(device_id, seq, event.id)` for their key, so that offline rebuilds do not fork forever.
34. As a listener, I want Device paired to be an idempotent upsert, so that pairing events can be replayed safely.
35. As a listener, I want author time (`created_at`) included in the signed Event payload, so that Peers cannot rewrite Playhead tie-break time without breaking the signature.
36. As a listener, I want Playhead merge within 2 minutes of author-time delta to prefer higher `position_seconds`, so that resume/scrub races keep the furthest progress.
37. As a listener, I want Playhead merge beyond 2 minutes of author-time delta to prefer later author time, so that a stale Device catching up does not clobber a newer listening session.
38. As a listener, I want two Peers that were offline with different Catalog edits to converge to the same Catalog after they meet and sync, so that “same events ⇒ same Catalog” holds even if apply order differs.
39. As a listener, I want to unpair a Peer via a replicated `DEVICE_UNPAIRED` event, so that the whole paired set stops trusting that Device’s future events.
40. As a listener, I want unpair to drop that Peer’s Locator hints and any buffered events from it, so that we do not keep trying a revoked Identity.
41. As a listener, I want already-applied Catalog effects from an unpaired Device’s past events to remain, so that history is not rewritten.
42. As a listener, I want re-pairing after unpair to require QR or short code again, so that trust is explicitly re-established.
43. As a listener, I want offline Reject undo (20s) to still stay local until commit, so that a mis-tap does not sync a Reject before I can undo.
44. As a listener, I want the phone demo and laptop demo to keep using the same DeviceAgent seam over HTTP or in-process connect, so that persistence and meet behavior are real in both setups.

## Implementation Decisions

- Follow ADR 0001 (Event log durable SoT) and ADR 0002 (Identity vs Locator / LAN meet). Vocabulary matches `CONTEXT.md`.
- Single seam remains the DeviceAgent. HTTP is transport to that agent; tests prefer constructing agents (and a fake LAN discovery/advertiser inject, same pattern as FakeSource) over calling storage or mDNS libraries directly.
- Durable on disk: append-only Event log as JSONL; small sidecar for local Device identity, trusted Peer identities, and last-known Locator hints. Catalog is not a separate durable store; cold start empties Catalog and replays the log.
- Local-only (not Event log): File bytes, Metered flag, in-progress Reject undo timer; private key material is durable locally and never replicated.
- Event signing includes `created_at` in the signed bytes along with id, type, device_id, and payload.
- Ingest dedupes by event id; verifies signature against the author’s known public key; buffers events whose author is not yet in Catalog until `DEVICE_PAIRED` (or equivalent) makes the author known.
- Sync between Peers in a proven session: full Event log pull both ways (or equivalent exchange), dedupe by id; incremental cursors are out of scope.
- Meet gate: before Catalog sync with a trusted Peer at a Locator, run challenge–response proving private-key possession. Session lasts until disconnect/failure; rediscovery or new hint after loss of reachability requires prove again.
- Locator hints are best-effort: try on meet paths; success still requires key proof; refresh hint after successful proof.
- LAN discovery: mDNS/DNS-SD. Advertise name, short code or key fingerprint, and enough to form a Locator. Fetch pairing payload for full public key before challenge. Browse on start, on network/interface change, and slow periodic while no trusted Peer has a live session. Same-LAN only.
- Trust establishment: QR or short code for first pair and for re-pair after unpair. Discovery of unknown keys only lists pair candidates.
- `DEVICE_UNPAIRED`: replicated; after apply, ignore that Device’s future events; drop its Locator hints and buffered events; keep past applied Catalog effects.
- Concurrent merge (same event set, any apply order):
  - Artist/Mix add, Device paired: idempotent upsert
  - Artist delete, Reject, Played: sticky
  - Stars, Tags (full list replace), Intent upsert/delete, Sequence, Assignment: last-by signed author time then `(device_id, seq, event.id)` (Intent delete beats older upsert)
  - Playhead: within 2 minutes author-time delta → higher `position_seconds`; else later author time
- Existing auto-sync and manual Sync remain; both must go through key-proved meet for remote Peers.
- Implementation tickets live under `.scratch/durable-sync/issues/` (01–07). Hackathon-demo issues 11 and 12 are `wontfix` (superseded); do not implement there.

## Testing Decisions

- A good test drives DeviceAgent the way the listener does and asserts Catalog, Peers, trust, and sync outcomes. It does not assert JSONL layout, mDNS wire format, or private helpers.
- Sole seam: DeviceAgent. Prior art: pair/sync/auto-sync/fill-cache agent tests under `tests/`.
- Persistence: new DeviceAgent instance with the same data directory after “restart”; assert Identity, trusted Peers, Locator hints, and Catalog (artists and other projected state) without re-pairing.
- Merge: two agents offline making conflicting Stars/Tags/Intent/Playhead edits, then meet + sync; assert identical Catalog; optionally assert order-of-ingest independence by applying peer event lists in different orders via the public sync path.
- Key proof: Locator that claims a trusted public key but cannot prove possession must not sync; after successful proof, Catalog sync proceeds; after session loss, proof is required again.
- Discovery: inject a fake advertiser/browser; trusted key advertisement → prove → hint refresh → sync; unknown key → pair candidate only until QR/short code.
- Unpair: after `DEVICE_UNPAIRED`, future events from that Device are ignored; hints/buffers cleared; prior Catalog rows from that author remain; re-pair needs QR/short code.
- Reject undo window and Metered behavior remain covered by existing agent tests; do not regress them.
- Live mDNS on a real LAN and real multi-process HTTP file copy are outside the default agent unit tests unless already patterned elsewhere; fake discovery covers the behavior contracts.

## Out of Scope

- Disposable Catalog snapshot cache (replay remains the only cold-start path).
- Incremental Event log sync cursors / `since`.
- SQLite or other DB-backed persistence (JSONL + sidecar only).
- Cross-network meet relay or required server-hosted Catalog.
- UDP discovery fallback alongside mDNS.
- Blockchain / ledger productization beyond the signed Event log.
- Changing audio File transfer beyond what already exists for in-process Peers (HTTP blob handoff remains a separate concern if still open).
- Bandcamp albums, OR tag filters, library/profile import, search, suggested tags — see `docs/LATER.md`.

## Further Notes

- Glossary and boundaries: root `CONTEXT.md`. Decisions: `docs/adr/0001-event-log-durable-source-of-truth.md`, `docs/adr/0002-identity-locator-and-lan-meet.md`.
- Related deferred items are listed under Planned features in `docs/LATER.md` (snapshot cache, incremental sync, SQLite, cross-network relay).
- `.scratch/hackathon-demo/issues/11-lan-peer-discovery.md` and `12-persist-peers.md` should be treated as pointers into this spec once work starts; prefer this spec’s acceptance language when they disagree with older one-liners.
