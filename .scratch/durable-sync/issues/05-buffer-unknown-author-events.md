# 05: Buffer unknown-author events

**What to build:** Events whose author Device is not yet in Catalog are buffered instead of silently dropped, then applied once that Device is paired into Catalog.

**Blocked by:** 01: Deterministic Catalog merge

**Status:** ready-for-agent

- [ ] Ingest does not silently drop events from an unknown author Device.
- [ ] Buffered events apply after the author becomes a known/paired Device in Catalog.
- [ ] Agent-level test: dependent events arrive before or without author pairing visibility, then pairing unlocks correct Catalog rows.
