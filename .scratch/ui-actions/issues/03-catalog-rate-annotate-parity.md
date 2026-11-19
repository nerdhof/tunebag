# 03: Catalog Rate + annotate refresh parity

**What to build:** Catalog browse can Rate a Release like Play history and Player. Annotate (Rate/Tag) from any of those surfaces keeps lists and Player chrome consistent via the refresh contract. Section tips / ⓘ copy match the annotate rules in `docs/UI-ACTIONS.md` (Catalog is an annotate surface; no “rate only on history” wording).

**Blocked by:** 01: Shared annotate control kit; 02: View-notice + refresh contract

**Status:** ready-for-agent

- [ ] Catalog Release rows expose interactive Rate through the shared annotate kit
- [ ] Rating or tagging from Catalog, Play history, or Player updates the other annotate surfaces without a manual Sync or filter toggle
- [ ] Section tips / ⓘ copy agree with Catalog-as-annotate and UI-ACTIONS verb rules
- [ ] CONTEXT / UI-ACTIONS Catalog Rate semantics are covered by tests
