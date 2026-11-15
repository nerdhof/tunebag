# 04: Key-proved meet

**What to build:** Before Event log sync with a trusted Peer at a Locator, the process there must prove possession of that Peer’s private key (challenge–response). A successful proof lasts only for the live meet/session.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Sync with a trusted Peer requires a successful challenge–response at the Locator.
- [ ] A Locator that claims a trusted public key but cannot prove possession does not sync Catalog.
- [ ] After proof, Catalog sync proceeds for that live session.
- [ ] After disconnect or loss of reachability, a new meet requires proving again.
- [ ] Agent-level tests cover success and impostor failure via the DeviceAgent seam.
