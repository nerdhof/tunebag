# mTLS Peer meet, split listeners, and Cache file share

Cleartext HTTP Locators let anyone on the LAN read Event pull and would expose File bytes the same way; challenge–response prove was client-side only and did not encrypt the channel. Peer meet is now mutual TLS on a dedicated Peer listener: each Device has a Device TLS cert (separate from the Event-signing keypair), Locators are HTTPS to that listener, and Event pull, File HEAD/GET, and peer fill/sync nudges require a live mTLS peer. Pairing may TOFU the peer cert into the existing PIN/SAS transcript; afterward a cert mismatch requires re-pair. The companion UI stays on a separate cleartext UI listener that does not serve Peer Event/File routes. Cache fill keeps pull semantics (`PeerBytes`), adds cheap completeness probes, and extends preferred-origin / supply / nudge to live HTTPS Peers so multi-process devices do not dual origin-fetch shared Assignments. In-process `connect()` remains for tests.

## Considered Options

- Opaque bearer over cleartext HTTP — rejected; snifflable and replayable on public WiFi.
- HTTPS server pin + app bearer — rejected for this pass; two mechanisms, weaker mutual auth story than mTLS.
- Application-layer body encryption without TLS — rejected; reinvents the channel and still leaks metadata.
- Single HTTPS port with browser client certs — rejected; breaks the companion UI; native clients later still prefer a local UI listener.
- Soft dual-mode unauthenticated Event pull — rejected; hard cut keeps one trust model.
- Push-based file handoff — rejected; existing fill policy and tests are pull/`ensure_complete`.
