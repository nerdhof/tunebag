# 02: CatalogJournal for local append, hold, export, and boot replay

**What to build:** Introduce CatalogJournal as the Event log spine for local Catalog writes and cold-start rebuild. DeviceAgent domain verbs append through the journal; multi-step Intent upsert + Sequence rebuild stays atomic under `hold` so peer `export` never sees a half-written Intent. Live apply runs `on_applied` (LocalEffects and unpair session cleanup only — not Catalog maintenance). Boot `replay` rebuilds Catalog only and does not run `on_applied`, so restart does not re-delete Files or intent folders.

**Blocked by:** 01 — Delete unused Catalog shim

**Status:** ready-for-agent

- [ ] CatalogJournal owns the Event log lock, per-author seq, dedupe set, sign/verify ports, and calls Catalog projection `apply`
- [ ] Interface includes `hold`, `append_local`, `replay`, and `export` (foreign ingest can wait for ticket 03)
- [ ] DeviceAgent local Catalog writes and boot replay use the journal
- [ ] Live `append_local` invokes `on_applied` under the lock; `replay` does not
- [ ] `on_applied` performs LocalEffects and unpair cleanup only — no Catalog maintenance triggers
- [ ] Intent upsert + rebuild under `hold` remains atomic w.r.t. `export`
- [ ] Journal-seam tests cover append → Catalog, replay without `on_applied`, and `hold`/`export` atomicity
- [ ] Existing persistence / projection regressions still pass
