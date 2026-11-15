# 06: Unpair (`DEVICE_UNPAIRED`)

**What to build:** The listener can unpair a Peer via a replicated `DEVICE_UNPAIRED` event. Future events from that Device are not trusted; Locator hints and buffers for it are dropped; already-applied Catalog effects remain. Re-pair requires QR or short code.

**Blocked by:** 02: Persist Identity + Event log; replay Catalog; 04: Key-proved meet

**Status:** ready-for-agent

- [ ] Unpair writes a replicated `DEVICE_UNPAIRED` event.
- [ ] After apply, that Device’s future events are ignored for Catalog.
- [ ] Locator hints and buffered events for that Peer are dropped.
- [ ] Past applied Catalog effects from that author remain.
- [ ] Re-establishing trust requires QR or short code again.
- [ ] Agent-level test covers unpair, ignored future events, retained history, and re-pair gate.
