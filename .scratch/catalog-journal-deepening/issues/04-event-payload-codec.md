# 04: Event payload codec for Intent and Release add

**What to build:** Own Intent and Release-add (`mix_added`, including Album tracks) payload encode/decode in one module so DeviceAgent and Catalog projection stop crossing a private encode/decode seam. Trivial scalar Event payloads stay inline. Legacy full-list tag Events remain decode-only in Catalog projection (ADR-0006).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Intent round-trip encode/decode lives in one payload module used by both writer and projection
- [ ] Release-add (`mix_added`) encode and matching decode helper live in that module, including Album track fields
- [ ] DeviceAgent no longer imports private projection decode helpers for Intent
- [ ] Round-trip tests cover Intent (including device hours / cleared device ids) and Mix vs Album `mix_added`
- [ ] Writers still emit per-tag add/remove; legacy `MIX_TAGGED` replay behavior unchanged
