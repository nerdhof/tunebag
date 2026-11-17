Status: ready-for-agent

# Bandcamp Album Releases

## Problem Statement

Listeners want Bandcamp albums in Tunebag the same way they already pull SoundCloud and hearthis artists: add a creator, get catalog rows, assign hours, fill cache, and play. Today Bandcamp URLs are rejected by the source router, there is no Album shape in the running Catalog (only glossary/ADR), and every listening item is assumed to be a single audio blob. Album-length music therefore cannot enter sequences or the player without pretending an album is one file or exploding into per-track catalog rows.

## Solution

Add a Bandcamp Artist adapter. The listener pastes an artist URL (`https://<artist>.bandcamp.com` or `…/music`). Tunebag lists that artist’s **full albums** only and ingests each as an **Album** **Release** (wire may still say `mix`). Duration and size are sums of tracks; ordered track metadata replicates in the Catalog; audio is fetched per track into one cache directory and is not “present” until every track is local. The Tunebag player plays tracks in order against a single album-timeline **Playhead**. Intent folders expose each Album as a subfolder of ordered track files. Reject, Skip, Rate, and Tag apply to the whole Release. Free/downloadable audio only in this pass.

Domain language: **Release** = **Mix** | **Album** (`CONTEXT.md`, ADR 0005). Code/API may keep `mix` / `mix_id` until a later rename.

## User Stories

1. As a listener, I want to add a Bandcamp artist via `https://<artist>.bandcamp.com/music`, so that their albums enter the shared Catalog like other platforms.
2. As a listener, I want `https://<artist>.bandcamp.com` (without `/music`) to normalize to the same Artist, so that I am not punished for omitting `/music`.
3. As a listener, I want pasting a Bandcamp album URL to fail with a clear error telling me to add the artist `/music` page, so that ingest stays “subscribe to a creator.”
4. As a listener, I want only full albums ingested (≥2 tracks and summed duration ≥ the configured minimum, default 20 minutes), so that singles and tiny EPs do not flood sequences.
5. As a listener, I want singles and one-track releases skipped, so that the Catalog stays album-shaped for Bandcamp.
6. As a listener, I want each ingested Bandcamp album to be an Album Release (not a separate catalog row per track), so that budgets and taste attach to the whole disc.
7. As a listener, I want SoundCloud and hearthis uploads to remain Mix Releases, so that existing DJ-set behavior does not change.
8. As a listener, I want Album duration to equal the sum of track durations, so that sequence budgets and Played % match real listening length.
9. As a listener, I want Album size (when known) to equal the sum of track sizes, so that cache planning stays honest.
10. As a listener, I want ordered track metadata (stable track ids, titles, durations, source permalinks) on the Album in the Catalog, so that every Peer can interpret the Release without re-scraping Bandcamp.
11. As a listener, I want that track metadata to replicate via the Event log with the Album add/upsert, so that offline Peers still know the track list.
12. As a listener, I want Album identity to be `(platform=bandcamp, platform_id=<Bandcamp album id>)` when the listing exposes a stable id, so that refresh does not duplicate rows.
13. As a listener, I want `url` on the Album to be the album page permalink, so that origin fetch and human inspection share one locator.
14. As a listener, I want adding a Bandcamp artist to create no audio bytes yet, so that cataloging stays cheap on metered links (same as today’s artist add).
15. As a listener, I want refresh of a known Bandcamp Artist to re-list and upsert new Albums without resurrecting committed Rejects or inventing duplicate platform ids, so that libraries grow safely.
16. As a listener, I want unsupported or non-free albums to be skipped or soft-failed at list/fetch without aborting the whole artist add, so that one locked release does not block the rest.
17. As a listener, I want Cache fill to download each Album track into one directory for that Release, so that playback can walk files in order.
18. As a listener, I want an Album to count as not present in Cache until every track file is local, so that partial discs are not treated as ready.
19. As a listener, I want incomplete Album directories cleaned up or retried rather than left as “has file,” so that fill stays deterministic.
20. As a listener, I want Peer copy of Album Files to transfer the whole track set (or leave the Album absent), so that Peers do not half-fill each other.
21. As a listener, I want Metered fill rules to treat an Album Release like any other assigned Release (current + one ahead), so that Bandcamp does not get a special metered policy.
22. As a listener, I want the Tunebag player to play Album tracks sequentially, so that an Album feels like one listening item.
23. As a listener, I want Playhead `position_seconds` to be on the concatenated Album timeline, so that existing Playhead merge rules keep working.
24. As a listener, I want resume to map timeline position onto the correct track file using Catalog track durations, so that scrub/resume works across Devices.
25. As a listener, I want Played at 75% of the Album’s summed duration (or explicit mark), so that finishing an album matches Mix semantics at Release scope.
26. As a listener, I want Last heard / Skip / Reject / Un-reject / Rate / Tag to apply to the whole Album Release, so that v1 has no per-track Catalog signals.
27. As a listener, I want Reject of an Album to delete its track files on every device after the undo window (same as Mix bytes), so that rejects free disk.
28. As a listener, I want intent folders to place each Mix as one file and each Album as a subfolder of ordered track files, so that external players can open a disc later.
29. As a listener, I want Sequences and Assignments to list Album Releases by the same id space as Mixes (wire `mix_id` ok), so that one sequence can mix DJ sets and albums.
30. As a listener, I want Catalog browse, Play history, and artist rollups to include Album Releases, so that Bandcamp discs are visible in the same UI surfaces.
31. As a listener, I want UI copy to be allowed to say Release / Album where easy, while APIs may still say mix, so that glossary-first rename does not block the feature.
32. As a listener, I want about/planned docs to describe Bandcamp as an Artist adapter producing Album Releases (not a vague “later primitive”), so that demo messaging matches the model.
33. As a paired listener, I want Album add events from one Device to appear on the other after sync, including track metadata, so that both Devices share the same Catalog.
34. As a listener, I want free/downloadable Bandcamp audio only in this pass, so that we do not build login/cookie purchase flows yet.
35. As a developer-agent, I want FakeSource to describe album-shaped listings and per-track bytes, so that DeviceAgent tests do not hit the network.
36. As a developer-agent, I want CompositeSource to route `*.bandcamp.com` artist URLs to the Bandcamp adapter, so that serve mode accepts Bandcamp the same way as SoundCloud/hearthis.

## Implementation Decisions

- Respect `CONTEXT.md` and ADR 0005: Catalog listening items are **Releases**; **Mix** = single-file Release; **Album** = ordered multi-track Release. Do not introduce a third top-level catalog entity.
- Glossary-first rename: domain and docs use Release/Mix/Album; persist/API/event field names may remain `mix` / `mix_id` / existing mix-add event types with an Album discriminant or equivalent subtype field. A dedicated rename pass is out of this spec.
- Extend the Source protocol/adapters: Bandcamp Artist listing returns album-shaped uploads (or a clear Album listing type) with nested ordered tracks; `CompositeSource` routes bandcamp.com artist hosts; reject bare `/album/…` URLs with an actionable error.
- Ingest path stays `add_artists` / `refresh_artists`: no separate “add album URL” API in this spec.
- Full-album filter: track count ≥ 2 and summed `duration_seconds` ≥ `min_duration_seconds` (same dial as today).
- Identity: `(Platform.BANDCAMP, bandcamp album id)` when available; one normalization used by add and refresh; Album `url` = album page.
- Catalog/Event: Album upsert carries ordered track metadata (stable track ids, titles, durations, permalinks). Bytes never go in the Event log.
- File/Cache: polymorphic — Mix = one blob; Album = directory of ordered track files for that release id. Album absent from Cache until all tracks local; incomplete dirs must not satisfy “has file.”
- Origin fetch: download tracks individually (yt-dlp or Bandcamp-capable fetcher); free/anonymous audio only; one bad album must not abort fill/list for the whole artist when avoidable.
- Player: sequential play of Album track files; Playhead remains one `position_seconds` on the Release timeline; derive track index locally from Catalog durations.
- Intent folders: Mix → single file; Album → subfolder with ordered track files (names stable enough for dumb external players).
- Reject / Skip / Rate / Tag / Played / Last heard: whole Release only; no per-track events.
- Peer file share: treat Album as an atomic cache unit (all tracks or not present).
- Update planned/about copy and LATER as needed so Bandcamp is described as this adapter, not an undefined future primitive (LATER already partially updated).
- Prefer extending FakeSource + DeviceAgent over new services; keep one primary behavioral seam.

## Testing Decisions

- Good tests assert external behavior through the highest seam: Catalog contents, Cache presence, play/resume/Played, intent-folder layout, and clear errors — not scraper HTML details or private helpers.
- **Primary seam:** `DeviceAgent` + extended `FakeSource` (album listings + per-track bytes), following prior art in add-artists, fill-caches, and play/rate/tag/resume tests.
- Cover: Bandcamp artist URL add/normalize; album URL rejected; full-album filter; Album Catalog fields (summed duration/size, track metadata, subtype); no bytes on add; fill all-or-nothing; sequential play + timeline Playhead/Played; whole-Release reject cleanup; intent-folder subfolder; refresh idempotent ids; Peer sync of Album metadata (and atomic cache expectations where fill tests already cover peers).
- **Secondary seam:** source routing — `*.bandcamp.com` artist URLs route to Bandcamp; unsupported hosts still error (extend existing source-routing tests).
- Prefer fakes over live Bandcamp/network in CI; optional marked integration tests only if the repo already patterns that for other platforms.

## Out of Scope

- Purchased Bandcamp, login/cookies, or download codes.
- Library import from `~/.music-snd-downloaded.txt` / on-disk purchases.
- Pasting album URLs as a supported ingest path.
- Per-track Reject, Skip, Rate, Tag, seek-bar track marks, or in-player track titles (explicit later).
- Concatenating tracks into a single blob.
- Renaming wire/API/events from `mix_*` to `release_*`.
- OR tag filters, Mixcloud, or other new platforms.
- Cross-network relay; changing Playhead merge rules.
- Making external players (Foobar/Vanilla) first-class signal sources.

## Further Notes

- Confirmed grill decisions live in conversation + `CONTEXT.md` + ADR 0005; implement against those, not older LATER wording that treated Album as only a future alternate primitive.
- Chris Huelsbeck-style URLs (`https://chrishuelsbeck.bandcamp.com/music`) are the canonical happy-path example for manual checks.
- Track-level UX and purchase/import remain valid follow-ups once Album Releases play end-to-end.
