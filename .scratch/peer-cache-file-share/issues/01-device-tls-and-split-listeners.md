# 01: Device TLS cert + split listeners

**What to build:** Persist a Device TLS cert with identity. Run UI listener (cleartext, companion) and Peer listener (HTTPS mTLS). Advertise/paste Peer Locator as the HTTPS URL. Pairing payload exposes cert for TOFU; trusted Peers pin fingerprint.

**Blocked by:** —

**Status:** ready-for-human

- [x] Generate/store Device TLS cert alongside Event-signing keys in the durable bag
- [x] `serve` binds UI port + Peer mTLS port; Locators / mDNS use Peer URL
- [x] Peer app mounts routes Peers hit; UI app does not serve File bytes or unauthenticated Event pull
- [x] Pairing TOFU records peer TLS fingerprint; re-meet requires pin match
- [x] Tests: identity cert round-trip; wrong cert rejected after trust; UI loads without client cert

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
- Implemented: Device TLS in identity bag; `create_ui_app` / `create_peer_app`; CLI `--peer-port` (HTTPS) + `--port` (UI); pairing payload + DEVICE_PAIRED pin; join/confirm transcripts include TLS fps. Live uvicorn HTTPS Peer + cleartext UI smoke test covers wire cert presentation. Issue 02 still owns CERT_REQUIRED hard-cut on Event pull.
