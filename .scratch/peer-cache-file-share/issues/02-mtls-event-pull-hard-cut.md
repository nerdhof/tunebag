# 02: mTLS Event pull hard cut

**What to build:** HTTP sync/pull uses Peer meet (mTLS client cert). Unauthenticated Event pull returns 401. Live meet is reachability-scoped mTLS (replaces client-only `/api/prove` as the gate).

**Blocked by:** 01: Device TLS cert + split listeners

**Status:** ready-for-human

- [x] Peer sync clients present Device TLS cert and verify peer pin
- [x] `POST /api/events/pull` on Peer listener requires mTLS client ∈ trusted Peers
- [x] Cleartext / no-cert pull fails in tests
- [x] Auto-sync nudges hit Peer listener over mTLS

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
- Implemented: Peer listener Event pull/export, `/api/sync` nudge, and yield require pinned client cert (401 without). Sync/nudge/yield HTTP clients present Device TLS + verify peer pin; mTLS meet replaces `/api/prove` as the HTTP gate. Peer SSLContext is CERT_OPTIONAL with CA of trusted peer PEMs (pairing TOFU stays open; unknown client cert fails handshake). Tests in `tests/test_mtls_event_pull_hard_cut.py`.
