# 04: Key-proved meet

**What to build:** Before Event log sync with a trusted Peer at a Locator, the process there must prove possession of that Peer’s private key (challenge–response). A successful proof lasts only for the live meet/session.

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] Sync with a trusted Peer requires a successful challenge–response at the Locator.
- [x] A Locator that claims a trusted public key but cannot prove possession does not sync Catalog.
- [x] After proof, Catalog sync proceeds for that live session.
- [x] After disconnect or loss of reachability, a new meet requires proving again.
- [x] Agent-level tests cover success and impostor failure via the DeviceAgent seam.

## Comments

- Implemented on DeviceAgent: `prove_possession` challenge–response before Event log pull; in-process proof cached until `disconnect`; HTTP Locators re-challenge every pull (`POST /api/prove`). Impostor claiming a trusted public key without the private key is skipped (no Catalog sync). Tests in `tests/test_key_proved_meet.py`.
