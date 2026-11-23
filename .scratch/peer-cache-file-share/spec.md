Status: ready-for-agent

# Peer meet (mTLS) and Cache file share

## Problem Statement

Paired Devices can sync Catalog over the network, but Cache fill still only copies Files between in-process agents. Two real `tunebag serve` processes each origin-fetch the same Assignments. Cleartext HTTP Locators also let anyone on the LAN read Event pull, and would expose File bytes the same way — unsafe on public Wi‑Fi.

## Solution

Each Device exposes a Peer listener over HTTPS with mutual TLS (Device TLS certs, pinned after pairing TOFU). Event pull, File presence probes, File byte GETs, and fill/sync nudges run only on that channel. Cache fill keeps pull semantics: prefer a live Peer that already has a complete Release, honor preferred-origin and Metered rules, and nudge waiting Peers after the preferred Device caches a File. A separate cleartext UI listener keeps the companion UI (and later native local clients) working without browser client certificates.

## User Stories

1. As a listener, I want my phone and laptop to be separate Device processes on the LAN, so that Cache fill works the way I actually run Tunebag.
2. As a listener, I want assigned File bytes to copy from a reachable Peer’s Cache before origin download, so that I do not burn mobile data or duplicate platform fetches.
3. As a listener, I want Peer and USB copies to count as unmetered, so that Metered mode only caps origin fetches.
4. As a listener, I want the highest-priority reachable Device whose Assignment includes a Release to origin-fetch it, so that the laptop does shared work when it is preferred.
5. As a listener, I want my phone to wait (no origin) while the preferred Peer is live but still missing bytes, so that we do not dual-download a shared Release.
6. As a listener, I want my phone to receive the File as soon as the preferred Peer has it, without waiting for that Peer’s extra hours to finish filling, so that listening can start early.
7. As a listener, I want Releases only in my device hours (not the Peer’s) to origin-fetch on my Device, so that exclusive Assignments still get audio.
8. As a listener, I want origin fetch to proceed when the preferred Peer is unreachable, so that I am not stuck offline for audio.
9. As a listener, I want a copy from any live trusted Peer that already has the complete Release to beat origin, so that opportunistic peer supply still helps.
10. As a listener, I want Cache fill to keep using pull (`ensure_complete` / PeerBytes), so that existing fill policy stays coherent.
11. As a listener, I want a cheap probe that a Peer has a complete Release before downloading multi‑MB bodies, so that fill stays actionable without wasteful GETs.
12. As a listener, I want Mix File share to be a single blob transfer, so that Mix Cache matches today’s local shape.
13. As a listener, I want Album File share only when the Peer has every track, so that Album presence stays all-or-nothing.
14. As a listener, I want a partial Album on a Peer to count as a miss, so that I never install an incomplete Album from a Peer.
15. As a listener, I want Album track bytes on the wire to map 1:1 to local track Files, so that Release Cache does not invent a packaging format.
16. As a listener, I want Peer meet traffic encrypted, so that Event NDJSON and File bodies are not readable on public Wi‑Fi.
17. As a listener, I want mutual authentication on Peer meet, so that a LAN attacker cannot impersonate my Peer at a Locator.
18. As a listener, I want captured Peer requests to be useless for replay by a third party, so that sniffing the café Wi‑Fi does not exfiltrate Catalog or Files later.
19. As a listener, I want each Device to have a Device TLS cert distinct from its Event-signing keypair, so that transport identity and Catalog authorship stay separate concerns.
20. As a listener, I want Peer Locators to be HTTPS addresses of the Peer listener, so that discovery and paste target the secure meet port.
21. As a listener, I want a cleartext UI listener for the companion UI, so that the browser does not need client certificates.
22. As a listener, I want the UI listener never to serve Peer Event pull or File bytes, so that cleartext local HTTP cannot leak the Peer surface.
23. As a listener, I want long-term native clients to keep talking to the local UI listener (local agent), so that replacing the companion UI does not reopen Peer meet to the UI toolkit.
24. As a listener, I want first-time pairing to TOFU the peer Device TLS cert into the PIN/SAS pairing transcript, so that public-Wi‑Fi pairing is not a permanent MITM hole.
25. As a listener, I want a later cert mismatch for a still-trusted Peer to require re-pair, so that a replaced or attacked endpoint cannot silently keep trust.
26. As a listener, I want re-meeting a still-trusted Peer to use discovery/hint plus mTLS pin match (no rescan), so that everyday reconnect stays automatic.
27. As a listener, I want Peer meet to last for the live session until disconnect, authenticated-call failure, or unpair, so that healthy traffic does not constantly re-handshake for policy.
28. As a listener, I want unauthenticated Event pull to fail hard, so that Catalog is not readable from a Locator without a trusted mTLS client.
29. As a listener, I want File HEAD/GET on the Peer listener to require the same mTLS trust, so that audio is not a weaker door than Catalog.
30. As a listener, I want fill and sync nudges between Peers to use the Peer listener under mTLS, so that background coordination is not a cleartext side channel.
31. As a listener, I want preferred-origin, “peer can supply,” and “nudge peers waiting on us” to treat live HTTPS Peers like in-process Peers, so that multi-process demos match PLAN priority rules.
32. As a listener, I want in-process `connect()` demos and unit tests to keep working without HTTPS, so that fast tests do not require a TLS stack.
33. As a listener, I want a shared peer-handle idea (id, priority, live, has Release, request fill) for in-proc and HTTPS Peers, so that fill policy is not forked.
34. As a listener, I want mDNS advertisements to carry enough to form a Peer Locator to the Peer listener, so that discovery reunites Devices on the secure port.
35. As a listener, I want pasted Peer Locators to keep working when mDNS is blocked, so that guest networks still allow meet after paste.
36. As a listener, I want Catalog sync on Metered links to keep working over Peer meet, so that plans travel even when origin audio is capped.
37. As a listener, I want Fill now and Metered origin allowlists to remain origin-only concerns, so that peer copies are not blocked by Metered.
38. As a listener, I want intent folders and local Cache layout to stay unchanged when Files arrive via Peer, so that playback and external folder consumers do not care about the transport.
39. As a listener, I want Un-reject and new Assignments to still obtain Files only via normal Cache fill (peer then origin), so that restore does not invent a special refetch path.
40. As a listener, I want Cover image bytes to stay out of this Peer File share, so that audio Cache work stays focused.
41. As a listener, I want USB File copy to remain a later transport, so that this pass closes the HTTPS gap first.
42. As a listener, I want vocabulary and boundaries for Device TLS cert, Peer meet, Peer listener, and UI listener documented in the domain glossary and ADR-0011, so that agents and humans do not re-litigate the channel.

## Implementation Decisions

- Vocabulary and boundaries follow `CONTEXT.md`. Wire meet and Cache file share follow ADR-0011; ADR-0002’s Identity vs Locator and pairing-for-trust still apply; cleartext client-only prove-as-meet is superseded.
- Split listeners on each Device: UI listener (cleartext, companion / future native local client) and Peer listener (HTTPS mTLS). Peer Locators, mDNS, paste/QR meet targets address the Peer listener only.
- Device identity gains durable Device TLS cert material alongside the Event-signing keypair. Trusted Peers persist pinned TLS cert fingerprints via pairing Events (TOFU at pair; pin thereafter).
- Peer meet = live mTLS with mutual cert verification against trusted pins (TOFU only during pairing). Session is reachability-scoped until disconnect, failure, or unpair.
- Hard cut: Event pull, File presence probe, File byte GET, and peer fill/sync nudges require Peer meet. No soft unauthenticated pull window.
- File wire mirrors PeerBytes: Mix = one blob; Album = complete-only, then per-track bytes. Presence via cheap HEAD/has. Incomplete Album → miss.
- Cache fill remains pull through Release Cache `ensure_complete`; DeviceAgent keeps urgency, Metered, preferred-origin policy.
- HTTPS Peers participate in preferred-origin wait, peer-supply checks, and fill nudges via a shared peer-handle abstraction (device id, priority, live, has_release, request_fill). Assignment and priority remain Catalog facts; live = Peer meet; has = probe; nudge = authenticated fill request on the Peer listener.
- In-process `connect()` remains for tests and same-process demos; it implements the same peer-handle semantics without TLS.
- Companion UI continues on the UI listener for this pass; native clients later replace the UI, not the Peer listener model.
- Implementation tickets: `.scratch/peer-cache-file-share/issues/` 01–04.

## Testing Decisions

- Good tests assert external Device behavior (who origin-fetches, who ends up with Files, what fails without trust, UI still serves locally) — not TLS library internals or private helper call graphs.
- Primary seam: two DeviceAgents with Peer listeners (mTLS) and FakeSource — same height as existing fill-cache tests, but over HTTPS Peer meet instead of `connect()` for multi-process acceptance stories.
- Secondary seam (keep existing): Release Cache with fake PeerBytes for Mix/Album completeness and `origin=None` wait — no HTTP required.
- Prior art: `tests/test_fill_caches.py`, `tests/test_metered_origin_downloads.py`, `tests/test_release_cache.py`, `tests/test_album_cache_and_intent_folders.py`, durable-sync / pairing HTTP agent tests.
- Required behavioral coverage: shared Assignment origin-once + peer copy; preferred-peer wait; exclusive hours origin on the non-preferred Device; unauthenticated/cleartext pull and File GET denied; cert pin reject after trust; Album partial peer → no copy; in-proc `connect()` regression still green; companion UI reachable on UI listener without client cert.

## Out of Scope

- USB File transport
- Peer transfer of Cover image bytes
- Push-based File handoff from preferred origin
- Removing or rewriting the companion UI (native clients are a later packaging effort)
- Cross-network meet relay
- Soft dual-mode cleartext Event pull
- Replacing Event-signing keys with TLS keys (they stay distinct)

## Further Notes

- Grill settled decisions are recorded in ADR-0011 and the glossary terms Device TLS cert, Peer meet, Peer listener, UI listener.
- Hackathon issue 04 already shipped in-proc fill; this feature closes the deferred HTTPS Peer file share and upgrades meet security.
- Long-term: native clients talk to the local UI listener; Peers never become the UI’s remote backend.
