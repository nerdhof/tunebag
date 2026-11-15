# 03: Play history annotate + resume

**What to build:** Play history becomes the annotate queue: from each row the listener can Rate, Tag, Reject (same 20s pending undo), one-click Un-reject when rejected, and resume playback at Playhead. A Rejected filter chip defaults off (muted when included). Catalog browse keeps stars display-only; rating edits stay on Play history and the player.

**Blocked by:** 01: Last heard from play; 02: Un-reject + Catalog reject UX

**Status:** ready-for-human

- [x] Play history rows support Rate and Tag against the Mix’s Catalog fields (same LWW behaviour as player / existing APIs)
- [x] Play history Reject uses the same pending undo pipeline as player and Catalog; committed rejected rows show Un-reject
- [x] Play history has a Rejected filter chip defaulting off; rejected rows are muted when shown
- [x] Resume from a History row loads that Mix into the player at the Catalog Playhead
- [x] Catalog mix rows do not gain star-edit controls (display only); annotate workflow stays on History + player
- [x] End-to-end behaviour verified via DeviceAgent where possible, plus the History/Catalog UI contracts the browser needs

## Comments

- Implemented: Play history Rejected filter (`#play-history-show-rejected`, `showRejectedHistory` default off); rows get Rate (`history-stars` → `/rate`), Tag, Reject/undo/Un-reject (same pending timer via `scheduleCatalogRejectRefresh`), muted `.mix-rejected`, Resume → `POST /api/player/play` with `mix_id` at Catalog Playhead. Catalog rating stays text-only. Tests in `tests/test_play_history_annotate_resume.py`.
