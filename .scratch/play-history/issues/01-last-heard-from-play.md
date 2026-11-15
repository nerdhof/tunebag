# 01: Last heard from play

**What to build:** When the listener plays a Mix past the meaningful-listen threshold, Tunebag records a Catalog-global Last heard on that Mix (rising edge only). Paired Devices converge on the same Last heard. A minimal Play history section lists Mixes that have a Last heard, newest first. No backfill for listens that happened before this feature.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Position reaching `max(120 seconds, 5% of duration)` emits a Last heard Event only when crossing that threshold from below (not on every playhead tick)
- [ ] Last heard is independent of Played and survives Event log rebuild / peer sync (latest Last heard wins under signed author time then `(device_id, seq, event.id)`)
- [ ] Mixes API (or equivalent Catalog read used by the UI) exposes Last heard so the client can order Play history
- [ ] Play history UI section lists Mixes with a Last heard, newest first (read-only annotate is enough for this ticket)
- [ ] Mixes that were only Played / playheaded before this feature do not appear in Play history until a new rising-edge listen
- [ ] Behaviour is verified through DeviceAgent (and HTTP only if needed for the list contract); prior art: play/rate/tag resume and mixes API artist tests
