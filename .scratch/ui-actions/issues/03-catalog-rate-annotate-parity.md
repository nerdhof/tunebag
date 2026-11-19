# 03: Catalog Rate + annotate refresh parity

**What to build:** Catalog browse can Rate a Release like Play history and Player. Annotate (Rate/Tag) from any of those surfaces keeps lists and Player chrome consistent via the refresh contract. Section tips / ⓘ copy match the annotate rules in `docs/UI-ACTIONS.md` (Catalog is an annotate surface; no “rate only on history” wording).

**Blocked by:** 01: Shared annotate control kit; 02: View-notice + refresh contract

**Status:** ready-for-human

- [x] Catalog Release rows expose interactive Rate through the shared annotate kit
- [x] Rating or tagging from Catalog, Play history, or Player updates the other annotate surfaces without a manual Sync or filter toggle
- [x] Section tips / ⓘ copy agree with Catalog-as-annotate and UI-ACTIONS verb rules
- [x] CONTEXT / UI-ACTIONS Catalog Rate semantics are covered by tests

## Comments

- Catalog `mountAnnotateKit` now uses `rateInteractive: true` + `refreshAfterTag: true` (same post-mutation path as History: `refreshAfterAnnotateMutation` → mixes/play_history force + player). Stars class `catalog-stars`. Catalog ⓘ tip lists Rate/tag/reject/Un-reject. Dropped UI-ACTIONS gap about display-only Catalog stars. Tests: `tests/test_catalog_rate_annotate_parity.py`; updated kit + play-history display-only contracts.
