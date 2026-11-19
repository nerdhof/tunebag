# 01: Cover URL ingest

**What to build:** Optional `cover_url` on Upload/Mix, MIX_ADDED codec, CONTEXT glossary, and per-platform parsing at `list_uploads`.

**Blocked by:** None

**Status:** ready-for-human

- [x] `Upload` and `Mix` have optional `cover_url`; `release_from_upload` threads it
- [x] `encode_mix_added` / `decode_mix_added` omit / default None
- [x] SoundCloud, hearthis, Bandcamp, YouTube listing extract cover URLs
- [x] CONTEXT notes Cover URL (Catalog) vs cover bytes (local)
