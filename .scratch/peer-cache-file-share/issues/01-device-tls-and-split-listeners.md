# 01: Device TLS cert + split listeners

**What to build:** Persist a Device TLS cert with identity. Run UI listener (cleartext, companion) and Peer listener (HTTPS mTLS). Advertise/paste Peer Locator as the HTTPS URL. Pairing payload exposes cert for TOFU; trusted Peers pin fingerprint.

**Blocked by:** —

**Status:** ready-for-agent

- [ ] Generate/store Device TLS cert alongside Event-signing keys in the durable bag
- [ ] `serve` binds UI port + Peer mTLS port; Locators / mDNS use Peer URL
- [ ] Peer app mounts routes Peers hit; UI app does not serve File bytes or unauthenticated Event pull
- [ ] Pairing TOFU records peer TLS fingerprint; re-meet requires pin match
- [ ] Tests: identity cert round-trip; wrong cert rejected after trust; UI loads without client cert

## Comments

- Spec: `.scratch/peer-cache-file-share/spec.md`. ADR-0011.
