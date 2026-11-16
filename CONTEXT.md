# Tunebag domain context

Canonical vocabulary for the codebase. Align code and docs with these terms.

## Glossary

- **Mix** — one audio file treated as a single listening item (typically a DJ set). Budgets and “played” use its duration.
- **Album** (later) — Bandcamp-style release treated as one listening item; duration is the sum of its tracks.
- **Artist** — a source-platform creator whose own uploads are ingested into the catalog.
- **Catalog** — the projected, fully replicated metadata on every paired device (artists, mixes, tags, ratings, rejects, play history, intents, sequences, assignments). Derived only from the Event log.
- **Tag** — free-text label; suggestions prefer existing tags. Intent membership uses AND of required tags.
- **Rating** — score 1–5 (UI may show ★). Separate from reject. Unrated mixes may still match a tagged intent.
- **Reject** — “never assign again” until Un-reject; after a 20s local undo window, bytes are deleted on every device.
- **Un-reject** — clears Reject on a Mix so it may re-enter sequences again. Does not by itself restore File bytes; Cache fill / peer / origin fetch run as usual when the Mix is assigned.
- **Rating distribution** — draw chances for 5★ / 4★ / 3★ / 2★ / 1★ / unrated (must sum to 1; default 0.3 / 0.2 / 0.1 / 0.05 / 0.05 / 0.3).
- **Intent** — shared plan: tag filter + rating distribution. Devices attach hours and optional expiry.
- **Sequence** — seeded ordered list of mixes for one intent. It fills until cumulative duration is at least the largest device budget, and may include the mix that crosses that budget.
- **Assignment** — which device hours cover which prefix of the sequence (independent of whether audio is on disk).
- **File** — audio bytes present on a device (local cache state).
- **Cache** — the set of files a device currently holds for its assignments.
- **Device** — a Tunebag installation with a stable identity (`device_id` + keypair) that authors Event log entries. Identity is not a network address.
- **Locator** — an ephemeral reachability hint for a Device (HTTP URL, IP:port, USB path, …). Locators change with the network; they are not Identity.
- **Peer** — another Device that has paired with this one and is reachable over LAN or USB, usable as a file source.
  _Avoid_: client (as a domain role)
- **Metered** — network mode that caps origin downloads to current mix + one ahead per intent.
- **Fill now** — one-shot override that fills one intent to its full device budget on a metered link.
- **Playhead** — last known position in a mix across Devices. Within 2 minutes of author-time delta, higher `position_seconds` wins; beyond 2 minutes, later author time wins.
- **Played** — listened past 75% of duration, or explicitly marked played.
- **Last heard** — Catalog-global timestamp on a Mix: the latest time any Device crossed the meaningful-listen threshold for that Mix. Threshold is position reaching `min(10 seconds, 2% of duration)`. Emit a Last heard Event only on the rising edge (position crosses the threshold from below); not on every playhead tick. Independent of Played. Merge keeps the latest Last heard (signed author time, then `(device_id, seq, event.id)`).
- **Play history** — UI section over Catalog Mixes that have a Last heard, ordered by Last heard (newest first). One row per Mix; not a list of play occurrences. No backfill: Last heard only from Events after the feature exists. Rejected Mixes via a Rejected filter (default off), muted when included. From this view: Rate, Tag, Reject (same 20s local pending undo as the player) or one-click Un-reject, and resume at Playhead.
  _Avoid_: listen log, play session, playback history (as a separate entity)
- **Catalog browse** — full Mix list (not Last-heard-ordered). Same Rejected filter (default off), Reject / Un-reject, and Tag as Play history. Rating controls stay on Play history and the player (Catalog may still display stars). Artist overview rows include a rejected Mix count (alongside other summary counts), even when the Rejected filter is off.
- **Event log** — the source of truth for Catalog: a signed append-only stream of catalog changes, replicated between paired Peers. Same events ⇒ same Catalog, independent of apply order (per-type deterministic merge). LWW fields order by signed author time then `(device_id, seq, event.id)`; Playhead uses the hybrid author-time rule above.
  _Avoid_: ledger, blockchain

## Boundaries

- Catalog replicates via the Event log. Audio does not, except as needed by assignments.
- Durable across restart: Device identity, trusted Peer identities (public keys / device ids), last-known Locators as non-authoritative hints, and the Event log. Catalog is rebuilt by replaying the Event log (a disposable snapshot cache may come later).
- Local-only (not Event log): File bytes, Metered flag, in-progress Reject undo timer, now-playing / local playback supervision, device private key material (key material is durable locally, not replicated).
- On Play, this Device best-effort asks reachable trusted Peers to yield local playback (pause if they are playing) so only one Device is audible. Unreachable Peers are left alone. Playing state is not an Event.
- Peers meet via LAN discovery and/or a listener-supplied Locator (paste/QR). A Locator never grants trust. Before sync, the process at that Locator must prove possession of the trusted Peer’s private key (challenge–response). Discovery matching a trusted public key may refresh Locator hints after proof; an unknown advertisement is only a pair candidate.
- LAN discovery uses mDNS/DNS-SD. Advertisements carry name, key fingerprint, and enough to form a Locator; the full public key is fetched (e.g. pairing payload) before challenge. Browse on agent start, on network/interface change, and with a slow periodic refresh while no trusted Peer has a live session. Discovery is same-LAN only (multicast domain); other networks use paste Locator or USB — no relay in this pass.
- Trust is established only via an ephemeral pairing session: one-time PIN (optional QR of the same offer), signed join, and dual-device Confirm of a matching SAS (first pair, or re-pair after unpair). Fingerprints label devices; they are not pairing secrets. Re-meeting a still-trusted Peer uses discovery/hint + key proof — no rescan.
- Peers exchange the full Event log when they can reach each other; dedupe by event id. Incremental cursors are a later optimization.
- Events whose author Device is not yet known are buffered until that Device is paired into the Catalog, not silently dropped.
- Concurrent Event log merge (same event set, any order): Artist/Mix add and Device paired are idempotent upserts; Artist delete and Played are sticky; Reject / Un-reject, Rating, Tags (full list replace), Intent metadata (name/tags/distribution/seed) upsert/delete, Sequence, Assignment, and Last heard use last-by signed author time then `(device_id, seq, event.id)` (Intent delete beats an older upsert under that order; Un-reject beats an older Reject under that order and vice versa; Last heard is latest timestamp under that order); Intent `device_hours` merge per `(intent_id, device_id)` under that same order (omission does not clear — removals carry explicit `cleared_device_ids` on the upsert); Playhead uses the hybrid rule above. Per-author `seq` is monotonic so same-Device rebuilds stay causal when `created_at` ties.
- Author time (`created_at`) is part of the signed Event payload.
- Unpair is a replicated `DEVICE_UNPAIRED` event: after it applies, that Device’s future events are not trusted for Catalog. Drop that Peer’s Locator hints and any buffered events from it; already-applied Catalog effects from its past events remain.
- A successful key proof at a Locator lasts for the live meet/session until disconnect or failure; rediscovery or a new hint after loss of reachability requires proving again.
- On disk (this hardening pass): append-only Event log (JSONL) plus a small sidecar for local Device identity, trusted Peer identities, and last-known Locator hints. Catalog is not a separate durable store.
- Our player is the source of play / rating / reject / tag / playhead signals in v1.
- External players may open intent folders; they do not write Tunebag signals in v1.
