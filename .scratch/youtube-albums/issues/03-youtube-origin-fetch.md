# 03: YouTube origin fetch with ejs, anonymous progressive audio

**What to build:** Cache fill for a YouTube Album track downloads progressive best audio anonymously. YouTube listing and fetch always enable remote JS components; no cookies in this pass. SoundCloud, hearthis, and Bandcamp fetch behavior stay unchanged. When YouTube blocks anonymous access, the listener gets a clear actionable error.

**Blocked by:** 01: YouTube Artist Source lists Album Releases

**Status:** ready-for-agent

- [ ] YouTube-host fetch uses progressive bestaudio (no extract-audio/ffmpeg requirement) and keeps noplaylist semantics for bare watch URLs.
- [ ] Remote JS components (`ejs:github`) are always enabled for YouTube listing and fetch.
- [ ] No cookies / cookies-from-browser in v1; auth/challenge failures surface actionable errors.
- [ ] Non-YouTube fetcher behavior is unchanged.
- [ ] Fetcher/option tests cover YouTube vs other hosts without live Google downloads in CI.
