# 02: Notices on Peer Event-log ingest

**What to build:** When this Device ingests a Peer’s Event log (manual sync or auto-sync), Catalog apply from those Events produces the same coalesced section notices as local writes. A listener’s open UI path is not required yet; in-process paired agents are enough to verify ingest → notices.

**Blocked by:** 01: Notice bus + coalesce on Catalog/Cache changes.

**Status:** ready-for-human

- [x] Ingesting Peer Events that add/change Mixes (and related taste fields) emits coalesced `mixes` / `play_history` as mapped in the spec.
- [x] Ingesting Intent / Sequence / Assignment Events emits a coalesced `intents` notice for the burst (not one per Event).
- [x] Ingesting Device paired/unpaired (or equivalent peer-set Catalog changes) emits `peers`.
- [x] Full-log catch-up apply coalesces per section for the ingest/sync pass.
- [x] Agent tests use in-process pair + sync/ingest; no browser required.

## Comments

- Foreign Event apply records sections into an `_ingest_notice_sink` flushed once per `sync` / `ingest_events` pass (no shared bus batch across threads). Tests in `tests/test_notices_on_peer_ingest.py`. SSE/UI remains issue 03.
