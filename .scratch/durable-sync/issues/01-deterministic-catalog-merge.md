# 01: Deterministic Catalog merge

**What to build:** Two Peers that edit Catalog offline (Stars, Tags, Intent, Playhead, and sticky Reject/Played) meet and end with the same Catalog regardless of apply order. Author time is signed; Playhead uses the hybrid 2-minute rule.

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] `created_at` is part of the signed Event payload.
- [x] Artist/Mix add and Device paired are idempotent upserts; Artist delete, Reject, and Played are sticky.
- [x] Stars, Tags (full list replace), Intent upsert/delete, Sequence, and Assignment use last-by signed author time then `(device_id, seq, event.id)` (Intent delete beats older upsert).
- [x] Playhead: within 2 minutes author-time delta → higher `position_seconds`; beyond → later author time.
- [x] Agent-level test: two Devices diverge offline, sync, assert identical Catalog (order-independent convergence).

## Comments

- Implemented on DeviceAgent: signed `created_at` + per-author `seq`; sticky delete/reject/played; LWW for tags/stars/intent/sequence/assignment; hybrid Playhead. Pure `(device_id, event.id)` as primary order made one Device dominate all LWW fields (broke expiry clears) — author time first, then `(device_id, seq, event.id)`. Tests in `tests/test_deterministic_catalog_merge.py`.
