# 05: Buffer unknown-author events

**What to build:** Events whose author Device is not yet in Catalog are buffered instead of silently dropped, then applied once that Device is paired into Catalog.

**Blocked by:** 01: Deterministic Catalog merge

**Status:** ready-for-human

- [x] Ingest does not silently drop events from an unknown author Device.
- [x] Buffered events apply after the author becomes a known/paired Device in Catalog.
- [x] Agent-level test: dependent events arrive before or without author pairing visibility, then pairing unlocks correct Catalog rows.

## Comments

- Implemented on DeviceAgent: `_unknown_author_buffer` holds events whose author is not yet in Catalog; `_ingest` no longer drops them. Flush on `DEVICE_PAIRED` (local `pair` or synced) via `_flush_buffered_events_for` (verify → append → apply, ordered by author time then seq). In-memory only this pass; unpair clearing is issue 06. Tests in `tests/test_buffer_unknown_author_events.py`.
