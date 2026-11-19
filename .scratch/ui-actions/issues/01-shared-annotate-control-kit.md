# 01: Shared annotate control kit

**What to build:** Player, Play history, and Catalog share one annotate control kit (Rate, Tag, Reject / undo-or-Un-reject as today) so later tickets do not triple-edit the same DOM. Product behaviour stays the same as before this ticket—no Catalog Rate parity yet, no Reject confirm-click / Soft-Hard yet.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] One shared annotate control kit mounts on Player, Play history, and Catalog Release rows
- [ ] Rate / Tag / Reject / Un-reject (and current undo chrome) behave as they did before this ticket on each surface that already had them
- [ ] Catalog stars remain display-only until ticket 03
- [ ] Regression coverage for annotate wiring (agent and/or UI contract tests) stays green
