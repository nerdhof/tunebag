Status: ready-for-agent

# Release cover art (player)

## Problem Statement

Releases carry no cover image. The player shows only Artist – Title text plus stars/tags, so the now-playing row is hard to recognize at a glance. Platform listings already expose artwork URLs that Tunebag ignores.

## Solution

Parse an optional `cover_url` at artist list/ingest into Catalog (`MIX_ADDED`). Cache image bytes device-locally under `data_dir/covers/` (not Event log, not audio Cache / metered fill). Serve `GET /api/mixes/{id}/cover` and show a thumbnail left of the player title/meta. Artist refresh backfills local covers for known Releases that still lack art.

## User Stories

1. As a listener, I want newly added Releases to store a cover URL from the source listing, so peers can lazy-fetch the same art without re-scraping.
2. As a listener, I want this Device to download cover bytes after add (and on refresh for known Releases missing local art), so the player can show a thumbnail offline once cached.
3. As a listener, I want the player to show cover art left of Artist – Release / stars / tags when art is available, so now-playing is recognizable.
4. As a listener, I want cover files deleted with audio on Reject / artist-delete cleanup, so rejected Releases do not leave orphan images.
5. As a listener, I do not need Catalog or Play history thumbs in this pass.

## Implementation Decisions

- Optional `cover_url` on `Upload` / `Mix`; omit from `mix_added` when None; decode missing → None.
- Local path: `data_dir/covers/<mix_id>` (outside `blobs/`).
- Soft-fail network errors on cover download (note + skip).
- No new Event type for backfill; refresh downloads from listing URL for known platform keys.
- Player only: `#player-cover` in `.player-below`; `/api/player` exposes `has_cover`.

## Out of Scope

- Catalog / History thumbnails
- Peer transfer of cover bytes
- Intent-folder / audio-tag embedding
