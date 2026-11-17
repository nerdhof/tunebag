# 01: YouTube Artist Source lists Album Releases

**What to build:** Listeners can paste a YouTube or YouTube Music channel URL and get album-shaped listings from the channel’s releases tab: official `OLAK` albums with ordered track metadata (titles, durations, video ids, bare watch permalinks). Deep links (watch, playlist, Music browse) fail with a clear “add the artist channel” error. Artist id is the channel id; album id is the `OLAK` playlist id.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [x] Channel forms (`@handle`, `/channel/UC…`, resolvable vanity; youtube.com and music.youtube.com) normalize so listing uses the releases tab.
- [x] Watch, playlist, and Music browse/album deep links are rejected with an actionable artist-channel error.
- [x] Listing returns only releases-tab `OLAK` album Uploads with ordered tracks from playlist context (not `/videos` or user `PL…` playlists).
- [x] Identities: Artist = channel id; Album = `OLAK` id + playlist URL; Track = video id + bare `watch?v=` URL.
- [x] Tests use injectable listing fakes (no live Google); cover normalize, reject, and album-shaped Uploads.

## Comments

- Implemented `YouTubeSource` with injectable `extract_info` (yt-dlp seam). Channel forms rewrite to `www.youtube.com…/releases`; deep links raise actionable errors. Only `OLAK…` releases-tab entries become Uploads; bad albums soft-skip. Identities: channel id / OLAK / video id + bare watch URL. Tests in `tests/test_youtube_source.py`. Composite routing and fetch-opts are issues 02–03.
