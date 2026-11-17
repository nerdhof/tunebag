# 04: Bandcamp Artist adapter

**What to build:** Listeners can add a Bandcamp artist (`https://<artist>.bandcamp.com` or `…/music`) and get real full albums end-to-end through the Album Release path (catalog, fill, play). Bare album URLs are rejected with a clear error. Only free/downloadable audio. Refresh does not duplicate album ids. Planned/about copy matches this adapter.

**Blocked by:** 03: Album play, Playhead, Played, Reject cleanup

**Status:** ready-for-agent

- [ ] CompositeSource routes `*.bandcamp.com` artist URLs to a Bandcamp adapter; `/music` and artist root normalize to the same Artist.
- [ ] Pasting a Bandcamp album page URL fails with an actionable error (add the artist `/music` page).
- [ ] Listing ingests only full albums (≥2 tracks, summed duration ≥ minimum); singles/one-track releases are skipped.
- [ ] Album identity uses `(bandcamp, album id)` when available; refresh does not create duplicates.
- [ ] Origin fetch uses free/downloadable audio only; locked/purchased-only releases are skipped or soft-failed without aborting the whole artist when avoidable.
- [ ] One bad album/track does not abort fill for unrelated Releases when avoidable (same spirit as existing fill resilience).
- [ ] About/planned (and LATER if needed) describe Bandcamp as this Artist → Album adapter, not an undefined later primitive.
