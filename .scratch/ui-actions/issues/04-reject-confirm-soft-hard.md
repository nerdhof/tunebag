# 04: Reject confirm-click, Soft/Hard, delayed File delete

**What to build:** Reject uses confirm-click, then appends a Reject Event immediately (no undo buffer). Snapshots expose Reject author time. Soft Rejected Releases stay in default Catalog and Play history lists (muted) for 5 minutes; Hard Rejected only with that surface’s Rejected filter. File bytes delete when Soft ages to Hard. Player offers Reject only; Catalog and Play history show Reject on normal Releases and Un-reject on Rejected ones. Invalidation uses the refresh/notice contract—not undo timers. See ADR-0007 and CONTEXT.

**Blocked by:** 01: Shared annotate control kit; 02: View-notice + refresh contract

**Status:** ready-for-agent

- [ ] Confirm-click Reject commits a Reject Event with no undo / `reject_pending_until` product path
- [ ] API/Catalog snapshots expose Reject author time (or equivalent) for the Soft window
- [ ] Soft Rejected rows appear muted in default Catalog and Play history; Hard Rejected only when that list’s Rejected filter is on; filters stay independent
- [ ] File bytes are not deleted until Soft → Hard (5 minutes from Reject author time)
- [ ] Player has Reject (confirm) and no Un-reject; lists have Reject or Un-reject by state
- [ ] Companion updates via the shared refresh/notice path after Reject / Un-reject (local and peer)
- [ ] Tests cover confirm commit, Soft/Hard visibility, delayed delete, and Un-reject during Soft vs after Hard
