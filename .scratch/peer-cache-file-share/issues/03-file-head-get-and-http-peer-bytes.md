# 03: File HEAD/GET + HTTP PeerBytes

**What to build:** Peer listener serves completeness probe + Mix/Album track bytes mirroring PeerBytes. HTTP PeerBytes adapter for `ensure_complete`. Incomplete Album → miss.

**Blocked by:** 01: Device TLS cert + split listeners

**Status:** ready-for-human

- [x] HEAD (or has) for complete Mix / complete Album only
- [x] GET Mix blob; GET Album track by index only when Album complete on server
- [x] HTTP PeerBytes `file_bytes` / `album_track_bytes` over mTLS
- [x] Tests: Album partial → no copy; probe before full GET

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
- Implemented: Peer listener `HEAD/GET /api/files/{mix_id}` + `GET .../tracks/{index}` behind mTLS; complete Mix/Album only (Album sets `X-Tunebag-Tracks`). `HttpPeerBytes` probes HEAD before body GET and plugs into `ensure_complete`. Partial Album → miss / no copy. UI listener does not serve File bytes. Tests in `tests/test_file_head_get_and_http_peer_bytes.py`. Issue 04 owns fill-policy / peer-handle parity for HTTPS Peers.
