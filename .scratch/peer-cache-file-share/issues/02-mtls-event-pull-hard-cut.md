# 02: mTLS Event pull hard cut

**What to build:** HTTP sync/pull uses Peer meet (mTLS client cert). Unauthenticated Event pull returns 401. Live meet is reachability-scoped mTLS (replaces client-only `/api/prove` as the gate).

**Blocked by:** 01: Device TLS cert + split listeners

**Status:** ready-for-agent

- [ ] Peer sync clients present Device TLS cert and verify peer pin
- [ ] `POST /api/events/pull` on Peer listener requires mTLS client ∈ trusted Peers
- [ ] Cleartext / no-cert pull fails in tests
- [ ] Auto-sync nudges hit Peer listener over mTLS

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
