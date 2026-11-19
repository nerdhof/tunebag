# 01: Delete unused Catalog shim

**What to build:** Remove the unused Catalog re-export shim so Catalog projection state is the only name callers use. Prefactor only — no behavior change.

**Blocked by:** None (can start immediately)

**Status:** claimed

- [ ] The shim module that only re-exports Catalog projection state is deleted
- [ ] Nothing in the package or tests still imports that shim alias
- [ ] Existing tests still pass
