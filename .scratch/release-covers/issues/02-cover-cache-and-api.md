# 02: Cover cache and API

**What to build:** Local `covers/` cache, ensure on add/refresh backfill, delete on reject, HTTP cover endpoint + `has_cover` on player.

**Blocked by:** 01

**Status:** ready-for-human

- [x] `data_dir/covers/<mix_id>`; `ensure_cover` soft-fails
- [x] `add_artists` / `refresh_artists` (known missing) download covers
- [x] `remove_local_file` also deletes cover
- [x] `GET /api/mixes/{id}/cover`; `/api/player` includes `has_cover`
