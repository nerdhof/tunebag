# 06: Unpair (`DEVICE_UNPAIRED`)

**What to build:** The listener can unpair a Peer via a replicated `DEVICE_UNPAIRED` event. Future events from that Device are not trusted; Locator hints and buffers for it are dropped; already-applied Catalog effects remain. Re-pair requires QR or short code.

**Blocked by:** 02: Persist Identity + Event log; replay Catalog; 04: Key-proved meet

**Status:** ready-for-human

- [x] Unpair writes a replicated `DEVICE_UNPAIRED` event.
- [x] After apply, that Device’s future events are ignored for Catalog.
- [x] Locator hints and buffered events for that Peer are dropped.
- [x] Past applied Catalog effects from that author remain.
- [x] Re-establishing trust requires QR or short code again.
- [x] Agent-level test covers unpair, ignored future events, retained history, and re-pair gate.

## Comments

- Implemented on DeviceAgent: `unpair(device_id)` appends `DEVICE_UNPAIRED`; apply revokes via `_revoke_peer` (remove from Catalog peers, drop Locator hint, clear buffered events, drop live proof). Sticky `_unpaired_device_ids` ignores that author’s future ingest (not buffered); remote `DEVICE_PAIRED` cannot restore trust — only local `pair` / short code. Past Catalog rows remain. Tests in `tests/test_unpair_device.py`.
- Listener surface: `POST /api/peers/{device_id}/unpair` returns peers payload; Peers list has confirm-to-unpair (⌫→💥). HTTP tests in `tests/test_web_unpair.py`.
- On apply, `_revoke_peer` also clears that Peer’s `device_hours` and assignments (intent rows stay). INTENT_UPSERTED / ASSIGNMENT_SET will not re-add hours/assignments for sticky-unpaired ids. UI notices: `peers` + `intents`.
