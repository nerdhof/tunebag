# 02: CatalogJournal for local append, hold, export, and boot replay

**What to build:** Introduce CatalogJournal as the Event log spine for local Catalog writes and cold-start rebuild. DeviceAgent domain verbs append through the journal; multi-step Intent upsert + Sequence rebuild stays atomic under `hold` so peer `export` never sees a half-written Intent. Live apply runs `on_applied` (LocalEffects and unpair session cleanup only — not Catalog maintenance). Boot `replay` rebuilds Catalog only and does not run `on_applied`, so restart does not re-delete Files or intent folders.

**Blocked by:** 01 — Delete unused Catalog shim

**Status:** ready-for-human

- [x] CatalogJournal owns the Event log lock, per-author seq, dedupe set, sign/verify ports, and calls Catalog projection `apply`
- [x] Interface includes `hold`, `append_local`, `replay`, and `export` (foreign ingest can wait for ticket 03)
- [x] DeviceAgent local Catalog writes and boot replay use the journal
- [x] Live `append_local` invokes `on_applied` under the lock; `replay` does not
- [x] `on_applied` performs LocalEffects and unpair cleanup only — no Catalog maintenance triggers
- [x] Intent upsert + rebuild under `hold` remains atomic w.r.t. `export`
- [x] Journal-seam tests cover append → Catalog, replay without `on_applied`, and `hold`/`export` atomicity
- [x] Existing persistence / projection regressions still pass

## Comments

- Extracted `CatalogJournal` (`src/tunebag/catalog_journal.py`). DeviceAgent wires local append / boot replay / export through it; foreign ingest still bridges via `hold` + `_apply_live` until ticket 03. Live `on_applied` still flushes unknown-author buffer on `DEVICE_PAIRED` (same order as pre-extract; 03 moves flush into the journal before `on_applied`). Journal-seam tests in `tests/test_catalog_journal.py`. Full suite: 343 passed; known-flaky `test_fill_caches_prunes_other` failed once in suite then passed alone.
