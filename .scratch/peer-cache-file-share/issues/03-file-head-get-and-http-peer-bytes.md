# 03: File HEAD/GET + HTTP PeerBytes

**What to build:** Peer listener serves completeness probe + Mix/Album track bytes mirroring PeerBytes. HTTP PeerBytes adapter for `ensure_complete`. Incomplete Album → miss.

**Blocked by:** 01: Device TLS cert + split listeners

**Status:** ready-for-agent

- [ ] HEAD (or has) for complete Mix / complete Album only
- [ ] GET Mix blob; GET Album track by index only when Album complete on server
- [ ] HTTP PeerBytes `file_bytes` / `album_track_bytes` over mTLS
- [ ] Tests: Album partial → no copy; probe before full GET

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
