# 03: CatalogJournal foreign ingest and unknown-author buffer

**What to build:** Move peer Event ingest onto CatalogJournal, including dedupe, signature verify, unpaired drop, and unknown-author buffering. After a live `DEVICE_PAIRED` apply, the journal flushes that author’s buffered Events (re-entrant ingest) before `on_applied`. The unknown-author buffer leaves Catalog projection state so the fold only sees trusted authors.

**Blocked by:** 02 — CatalogJournal for local append, hold, export, and boot replay

**Status:** ready-for-agent

- [ ] `ingest_foreign` lives on CatalogJournal with today’s silent skips (dedupe, self-authored, unpaired)
- [ ] Unknown-author Events buffer on the journal, not on Catalog projection state
- [ ] After live `DEVICE_PAIRED`, journal flushes that author’s buffer under the same lock before `on_applied`
- [ ] `InvalidSignature` still fails fast on verify
- [ ] DeviceAgent sync/peer pull uses journal ingest
- [ ] Tests show buffered Events apply only after pair; prefer the journal seam, keep a DeviceAgent regression if useful
- [ ] No public buffer inspection API
