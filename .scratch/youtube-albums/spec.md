Status: ready-for-agent

# YouTube Album Releases

## Problem Statement

Listeners want official YouTube / YouTube Music discographies in Tunebag the same way they already pull Bandcamp artists: paste a creator URL, get Album Releases in the Catalog, assign hours, fill cache, and play. Today `Platform.YOUTUBE` exists but no Source routes `youtube.com` or `music.youtube.com`, so those URLs are rejected. YouTube Music artist pages look like album homes in the browser, but yt-dlp treats Music as a skin over YouTube and defaults bare `@handle` URLs to the videos tab — not the releases discography — so “add this Music artist” would silently mean the wrong thing without an explicit Album-shaped Source.

## Solution

Add a YouTube Artist Source. The listener pastes a YouTube or YouTube Music channel URL (`@handle`, `/channel/UC…`, or resolvable vanity forms). Tunebag normalizes to the channel’s **releases** tab, lists official album playlists (`OLAK…`) only, and ingests each as an **Album** **Release** (same Catalog/Cache/player path Bandcamp already uses). Track metadata comes from playlist context (titles, order, video ids), not unreliable per-video music tags. Listing and origin fetch stay **anonymous** (no cookies); YouTube yt-dlp calls always enable **remote JS components** (`ejs:github`). Progressive `bestaudio` download — no extract-audio/ffmpeg requirement in this pass. SoundCloud and hearthis remain Mix-only; Bandcamp behavior unchanged.

Domain language: **Release** = **Mix** | **Album** (`CONTEXT.md`). YouTube Music is a URL/UI skin, not a separate Catalog platform — store `Platform.YOUTUBE`.

## User Stories

1. As a listener, I want to add a YouTube artist via `https://www.youtube.com/@HANDLE`, so that their official albums enter the shared Catalog like Bandcamp.
2. As a listener, I want `https://music.youtube.com/@HANDLE` to work the same way, so that copying a YouTube Music artist link is not a dead end.
3. As a listener, I want `@HANDLE`, `@HANDLE/releases`, and Music-domain equivalents to normalize to one Artist identity, so that I am not punished for which host or tab I copied.
4. As a listener, I want `/channel/UC…` (and vanity `/c/…` / `/user/…` when yt-dlp can resolve them) to be accepted and listed via that channel’s releases tab, so that non-handle links still work.
5. As a listener, I want pasting a watch URL, playlist URL, or Music `browse/MPREb…` album URL to fail with a clear error telling me to add the artist channel, so that ingest stays “subscribe to a creator.”
6. As a listener, I want pasting `/videos` or `/playlists` tab URLs to fail or be rewritten only after explicit policy — in this pass, accept channel forms and always **list** via `/releases`, so Videos and user playlists never become the discography source.
7. As a listener, I want only `/releases` entries that resolve to `OLAK…` album playlists ingested as Albums, so that user `PL…` playlists and promo video dumps do not flood the Catalog.
8. As a listener, I want full-album filtering (≥2 tracks and summed duration ≥ the configured minimum, default 20 minutes), so that singles and tiny releases are skipped the same way as Bandcamp.
9. As a listener, I want each ingested YouTube album to be an Album Release (not a Mix and not one Catalog row per track), so that budgets and taste attach to the whole disc.
10. As a listener, I want Album identity to be `(platform=youtube, platform_id=<OLAK playlist id>)`, so that refresh does not duplicate rows.
11. As a listener, I want Artist identity to be `(platform=youtube, platform_id=<channel id UC…>)`, so that handle renames do not fork the Artist.
12. As a listener, I want the Album `url` to be the canonical `youtube.com/playlist?list=OLAK…` permalink, so that origin inspection and humans share one locator.
13. As a listener, I want each track’s stable id to be the YouTube video id and its permalink a bare `watch?v=` URL, so that per-track fetch stays `noplaylist`-safe and dedupe-stable.
14. As a listener, I want track titles, order, and durations to come from the album playlist listing (playlist title / entry title / playlist index / entry duration), so that Catalog metadata works even when yt-dlp leaves `album` / `track` / `track_number` null on label uploads.
15. As a listener, I want adding a YouTube artist to create no audio bytes yet, so that cataloging stays cheap on metered links.
16. As a listener, I want refresh of a known YouTube Artist to re-list and upsert new Albums without resurrecting committed Rejects or inventing duplicate platform ids, so that libraries grow safely.
17. As a listener, I want one bad album or track to soft-fail without aborting the whole artist list or unrelated fills, so that fragile YouTube responses do not brick the Artist.
18. As a listener, I want Cache fill, atomic Album presence, sequential play, timeline Playhead, Played, Reject, Skip, Rate, Tag, intent folders, Sequences, and Peer metadata sync to treat YouTube Albums exactly like Bandcamp Albums, so that YouTube does not invent a second Album runtime.
19. As a listener, I want origin fetch to stay anonymous (no browser cookies file in v1), so that Devices do not depend on a logged-in Firefox profile.
20. As a listener, I want YouTube yt-dlp listing and fetch to always use remote JS components (`ejs:github`), so that intermittent YouTube JS challenges are less likely to break ingest and fill.
21. As a listener, I want progressive best-audio download without requiring ffmpeg extract-audio, so that YouTube fill matches Tunebag’s existing fetcher philosophy.
22. As a listener, I want a clear actionable error when anonymous YouTube fetch fails due to auth/challenge restrictions, so that I know the Device cannot fill that track right now (cookies remain a later escape hatch, not this pass).
23. As a listener, I want SoundCloud and hearthis uploads to remain Mix Releases and Bandcamp to keep its Artist → Album behavior, so that existing platforms do not change.
24. As a listener, I want YouTube Music not to appear as a separate Catalog platform, so that one Artist is not split between “YouTube” and “YouTube Music.”
25. As a listener, I want about/planned docs (and LATER if needed) to describe YouTube as an Artist Source producing Album Releases from the releases tab, so that demo messaging matches the model.
26. As a paired listener, I want YouTube Album add events (including track metadata) to replicate via the Event log like other Album Releases, so that Peers share the same Catalog.
27. As a developer-agent, I want FakeSource to keep covering Album-shaped DeviceAgent behavior, so that YouTube work does not re-litigate Catalog/Cache/player Album semantics.
28. As a developer-agent, I want CompositeSource to route `youtube.com` and `music.youtube.com` to the YouTube Source, so that serve mode accepts those Artist URLs.
29. As a developer-agent, I want CI tests to use fakes/injectable yt-dlp seams rather than live Google, so that the suite stays deterministic.
30. As a domain reader, I want CONTEXT to note that Artist listing shape is platform-defined (e.g. SC/hearthis → Mix uploads; Bandcamp/YouTube → Album discography), so that “own uploads” is not misread as YouTube `/videos` only.

## Implementation Decisions

- Respect `CONTEXT.md`: Catalog listening items are **Releases**; **Mix** = single-file; **Album** = ordered multi-track. Do not introduce a third catalog entity or a `YOUTUBE_MUSIC` platform.
- Extend the Source protocol implementations with a YouTube Artist Source; CompositeSource routes youtube.com and music.youtube.com hosts (www-stripped). Unsupported hosts still error with an updated allow-list message.
- Ingest path stays `add_artists` / `refresh_artists`: no supported “add album/playlist/watch URL” API in this spec.
- URL policy: accept `@handle` (with or without `/releases`), Music-domain equivalents, `/channel/UC…`, and vanity forms yt-dlp can resolve to a channel; normalize listing URL to that channel’s `/releases` tab on www.youtube.com when possible. Reject watch, `playlist?list=`, and `browse/MPREb…` (and similar album-deep links) with actionable “add the artist channel” errors.
- Discography: only `/releases` entries that are `OLAK…` album playlists become Uploads. Ignore channel `/videos`, `/playlists` (`PL…`), and Mix-shaped single videos in this pass.
- Full-album filter remains the existing Catalog ingest rule (track count ≥ 2 and summed duration ≥ min duration); Source may return thinner candidates, but DeviceAgent filtering must continue to apply.
- Identity: Artist `platform_id` = channel id (`UC…`); Album Upload `platform_id` = `OLAK…`; Track `platform_id` = video id. Album URL = `https://www.youtube.com/playlist?list=OLAK…`. Track URL = bare `https://www.youtube.com/watch?v=VIDEO`.
- Track Catalog fields: title from playlist entry title; order from playlist index / entry order; duration from entry duration when present; do not require yt-dlp `album` / `artist` / `track` / `track_number` fields (often null on official label uploads).
- Listing uses yt-dlp extract/info style flat playlist against `/releases` then per-album playlist expansion; always enable remote JS components (`ejs:github`) for YouTube listing and fetch. No cookies / cookies-from-browser in v1.
- Origin fetch: reuse the shared audio fetcher with YouTube-host-specific opts (ejs always; progressive `bestaudio/best`; keep `noplaylist`; no extract-audio postprocessor). Leave SoundCloud/hearthis/Bandcamp fetcher behavior unchanged. Prefer free/progressive formats; no ffmpeg merge requirement in this pass.
- Auth failures: surface clear errors; do not silently attach browser cookies. Optional cookies-file support is out of scope (document in LATER if mentioned).
- Reuse existing Album Release runtime (Cache directory of tracks, sequential play, timeline Playhead, whole-Release signals, intent-folder subfolders). YouTube only supplies album-shaped Uploads into that path.
- Normalize Artist URLs in the same spirit as Bandcamp normalization so add/refresh dedupe by canonical form.
- Update CONTEXT glossary note on Artist listing being platform-defined; update about/planned and LATER so YouTube is described as this Source, not an undefined primitive.
- Prefer injectable listing/fetcher seams for tests; one primary behavioral seam for new logic (YouTube Source), plus routing and yt-dlp-opt tests.

## Testing Decisions

- Good tests assert external behavior: normalized Artist URLs, rejected deep links, ArtistListing platform/ids, album-shaped Uploads with ordered tracks, Composite routing, and YouTube-specific yt-dlp options — not InnerTube HTML or private helper structure.
- **Primary seam:** YouTube Source with injectable yt-dlp/listing (prior art: Bandcamp Source tests). Cover accept/normalize channel forms; reject watch/playlist/browse; releases → OLAK albums with track metadata from playlist context; channel id / OLAK / video id identity; soft-skip of unusable albums when avoidable.
- **Secondary seam:** CompositeSource host dispatch (prior art: source routing tests) for youtube.com and music.youtube.com list + fetch.
- **Secondary seam:** shared audio fetcher opts (prior art: yt-dlp fetch tests) — YouTube hosts enable ejs/remote components; no cookies; progressive bestaudio; non-YouTube hosts unchanged.
- Do **not** re-prove DeviceAgent Album Catalog/Cache/player behavior unless YouTube-specific Artist URL normalization at add_artists needs a thin case; FakeSource Album coverage from the Bandcamp Album work remains the Album runtime seam.
- Prefer fakes over live YouTube/Google in CI; no required network integration tests in this pass.

## Out of Scope

- Browser cookies, cookies file, or cookies-from-browser for YouTube.
- `--extract-audio` / ffmpeg remux as a YouTube requirement.
- Ingesting YouTube `/videos` as Mix Releases.
- Ingesting user `PL…` playlists or Music search results as Albums.
- Pasting watch, playlist, or `MPREb` browse URLs as a supported ingest path.
- A separate `YOUTUBE_MUSIC` Catalog platform.
- Per-track Catalog signals (Reject/Skip/Rate/Tag).
- Purchased/premium-only YouTube Music gating beyond “anonymous fetch failed” errors.
- Renaming wire/API/events from `mix_*` to `release_*`.
- Changing Bandcamp, SoundCloud, or hearthis behavior.
- ADR for “Music skin ≠ new platform” (CONTEXT note is enough unless a future surprise warrants one).

## Further Notes

- Grill decisions (conversation): Artist-only paste; Albums from `/releases` `OLAK` only; `Platform.YOUTUBE`; anonymous fetch; ejs always on YouTube list+fetch; progressive bestaudio; scratch feature `.scratch/youtube-albums/`; CONTEXT Artist platform-defined listing note.
- Canonical manual example: `https://music.youtube.com/@TOOLmusic` → normalize/list `https://www.youtube.com/@TOOLmusic/releases` (yt-dlp warns that Music is redirected to youtube.com).
- Empirically, TOOL official album tracks often lack yt-dlp `album`/`track_number` even with cookies; playlist_title / playlist_index / entry title are the reliable metadata source.
- Album runtime (fill, play, Playhead, intent folders) is already shipped via the Bandcamp Album work; this spec is the YouTube Source + routing + fetch-opts + docs slice.
- Topic / Music-only channels without a `/releases` tab (auto-generated `Artist - Topic` UC channels) still normalize to `…/releases`, then list via YouTube Music InnerTube browse for first-page `OLAK…` album cards (issue 05).
