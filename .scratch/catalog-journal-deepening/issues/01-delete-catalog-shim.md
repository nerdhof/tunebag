# 01: Delete unused Catalog shim

**What to build:** Remove the unused Catalog re-export shim so Catalog projection state is the only name callers use. Prefactor only — no behavior change.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [x] The shim module that only re-exports Catalog projection state is deleted
- [x] Nothing in the package or tests still imports that shim alias
- [x] Existing tests still pass

## Comments

- Deleted unused `src/tunebag/catalog.py` (`CatalogState as Catalog` re-export). Callers already use `tunebag.projection.CatalogState`. Full suite: 336 passed (1 deselected known-flaky `test_fill_caches_prunes_other`, fails intermittently with or without this change).
