# 03: CatalogJournal foreign ingest and unknown-author buffer

**What to build:** Move peer Event ingest onto CatalogJournal, including dedupe, signature verify, unpaired drop, and unknown-author buffering. After a live `DEVICE_PAIRED` apply, the journal flushes that author’s buffered Events (re-entrant ingest) before `on_applied`. The unknown-author buffer leaves Catalog projection state so the fold only sees trusted authors.

**Blocked by:** 02 — CatalogJournal for local append, hold, export, and boot replay

**Status:** ready-for-human

- [x] `ingest_foreign` lives on CatalogJournal with today’s silent skips (dedupe, self-authored, unpaired)
- [x] Unknown-author Events buffer on the journal, not on Catalog projection state
- [x] After live `DEVICE_PAIRED`, journal flushes that author’s buffer under the same lock before `on_applied`
- [x] `InvalidSignature` still fails fast on verify
- [x] DeviceAgent sync/peer pull uses journal ingest
- [x] Tests show buffered Events apply only after pair; prefer the journal seam, keep a DeviceAgent regression if useful
- [x] No public buffer inspection API

## Comments

- Moved foreign ingest + unknown-author buffer onto `CatalogJournal.ingest_foreign` / private buffer. Live `DEVICE_PAIRED` flushes before `on_applied`; `DEVICE_UNPAIRED` drops that author’s buffer. Buffer removed from `CatalogState`. DeviceAgent `_ingest` delegates to the journal; foreign UI notices record from `_on_journal_applied`. Journal-seam tests in `tests/test_catalog_journal.py`; DeviceAgent regressions in `tests/test_buffer_unknown_author_events.py`. Full suite: 357 passed.
