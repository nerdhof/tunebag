# 01: Shared annotate control kit

**What to build:** Player, Play history, and Catalog share one annotate control kit (Rate, Tag, Reject / undo-or-Un-reject as today) so later tickets do not triple-edit the same DOM. Product behaviour stays the same as before this ticket—no Catalog Rate parity yet, no Reject confirm-click / Soft-Hard yet.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] One shared annotate control kit mounts on Player, Play history, and Catalog Release rows
- [x] Rate / Tag / Reject / Un-reject (and current undo chrome) behave as they did before this ticket on each surface that already had them
- [x] Catalog stars remain display-only until ticket 03
- [x] Regression coverage for annotate wiring (agent and/or UI contract tests) stays green

## Answer

Prefactor only: `mountAnnotateKit` in `src/tunebag/static/app.js` is the single entry point for annotate chrome.

- **Catalog / History (row mode):** `mountRowAnnotateKit` builds Rate + Reject/Undo/Un-reject + Tag into the row; Catalog keeps `rateInteractive: false`; History keeps interactive Rate and `refreshAfterTag: true`.
- **Player:** `mountPlayerAnnotateKit` binds the long-lived `#player-stars` / reject / undo / tag roots (still no Un-reject); `updateRejectControls` delegates to the kit.
- Behaviour unchanged vs pre-ticket (undo Reject window, Catalog display-only stars). Contract: `tests/test_shared_annotate_control_kit.py` plus existing play-history / catalog reject UI contracts.
