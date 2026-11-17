# 05: Topic channels list albums via Music browse fallback

**What to build:** When a YouTube / Music channel URL normalizes to `/releases` but the channel has no releases tab (auto-generated Topic channels), fall back to YouTube Music InnerTube browse for `OLAK…` album cards. Do not restructure URL normalization or introduce a separate Music platform.

**Blocked by:** 01: YouTube Artist Source lists Album Releases

**Status:** ready-for-human

- [x] Missing-releases-tab extract errors trigger Music browse fallback (injectable seam).
- [x] Browse yields unique `OLAK…` from `MUSIC_PAGE_TYPE_ALBUM` two-row cards; albums expand via existing playlist listing.
- [x] Topic suffix stripped from artist name; canonical `listing.url` stays the `/releases` form for dedupe/refresh.
- [x] Tests cover Topic Music URL fallback, releases path without browse, and name stripping (no live Google).

## Comments

- Root cause for Käptn Peng / Tentakel Music channel links: UC Topic channels have no `/releases` tab (yt-dlp#9673). Normalization already accepted `/channel/UC…`. Fallback uses WEB_REMIX InnerTube browse via httpx; first-page Albums/Singles carousels only.
