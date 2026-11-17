# 03: YouTube origin fetch with ejs, anonymous progressive audio

**What to build:** Cache fill for a YouTube Album track downloads progressive best audio anonymously. YouTube listing and fetch always enable remote JS components; no cookies in this pass. SoundCloud, hearthis, and Bandcamp fetch behavior stay unchanged. When YouTube blocks anonymous access, the listener gets a clear actionable error.

**Blocked by:** 01: YouTube Artist Source lists Album Releases

**Status:** ready-for-human

- [x] YouTube-host fetch uses progressive bestaudio (no extract-audio/ffmpeg requirement) and keeps noplaylist semantics for bare watch URLs.
- [x] Remote JS components (`ejs:github`) are always enabled for YouTube listing and fetch.
- [x] No cookies / cookies-from-browser in v1; auth/challenge failures surface actionable errors.
- [x] Non-YouTube fetcher behavior is unchanged.
- [x] Fetcher/option tests cover YouTube vs other hosts without live Google downloads in CI.

## Comments

- Shared fetcher enables `remote_components=["ejs:github"]` for YouTube hosts only; progressive `bestaudio/best` + `noplaylist` + no cookies/extract-audio. Auth/bot gates re-raise as actionable `ValueError` (listing via `_youtube_extract_info`, fetch via `ytdlp_fetch`). Tests in `tests/test_ytdlp_fetch.py` and listing opts/auth in `tests/test_youtube_source.py`.
