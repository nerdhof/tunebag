# 04: Fill policy parity for HTTPS Peers

**What to build:** Shared peer-handle for in-proc and HTTPS Peers. Preferred-origin wait, peer supply, and nudge waiting peers work across two serve processes over Peer meet.

**Blocked by:** 02: mTLS Event pull hard cut; 03: File HEAD/GET + HTTP PeerBytes

**Status:** ready-for-agent

- [ ] Preferred-origin / supply / nudge no longer in-proc-only
- [ ] Fill nudge via authenticated request on Peer listener
- [ ] Integration test: two agents over mTLS — shared Release origin once, peer copy to the other
- [ ] In-proc `connect()` path still green without HTTPS

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011. Primary acceptance seam.
