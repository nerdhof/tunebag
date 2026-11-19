# 04: Event payload codec for Intent and Release add

**What to build:** Own Intent and Release-add (`mix_added`, including Album tracks) payload encode/decode in one module so DeviceAgent and Catalog projection stop crossing a private encode/decode seam. Trivial scalar Event payloads stay inline. Legacy full-list tag Events remain decode-only in Catalog projection (ADR-0006).

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [x] Intent round-trip encode/decode lives in one payload module used by both writer and projection
- [x] Release-add (`mix_added`) encode and matching decode helper live in that module, including Album track fields
- [x] DeviceAgent no longer imports private projection decode helpers for Intent
- [x] Round-trip tests cover Intent (including device hours / cleared device ids) and Mix vs Album `mix_added`
- [x] Writers still emit per-tag add/remove; legacy `MIX_TAGGED` replay behavior unchanged

## Comments

- Added `tunebag.event_payloads` with `encode_intent`/`decode_intent` and `encode_mix_added`/`decode_mix_added`. DeviceAgent and Catalog projection both use it; agent no longer imports projection’s private Intent decode. Round-trip tests in `tests/test_event_payloads.py`. Tag writers and `MIX_TAGGED` replay left untouched.
