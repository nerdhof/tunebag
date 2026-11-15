# 11: Discover Tunebag agents on the local network

**What to build:** A Device can find other Tunebag agents on the LAN without the listener pasting a Locator. mDNS/DNS-SD advertise + browse; discovery refreshes reachability for already-trusted Peers after key proof; unknown ads are pair candidates only (QR or short code). See ADR 0002 and `CONTEXT.md`.

**Blocked by:** 01: Pair two devices

**Status:** wontfix

- [ ] Running agents advertise on the LAN via mDNS (name, short code/fingerprint, enough to form a Locator).
- [ ] Browse on agent start, on network/interface change, and with slow periodic refresh when no trusted Peer has a live session.
- [ ] Full public key is fetched (pairing payload) before challenge; discovery alone does not trust.
- [ ] Trusted public key + successful challenge → refresh Locator hint and sync; unknown → pair candidate (QR/short code).
- [ ] Pasted Locator and QR pairing continue to work when discovery is unavailable (same-LAN only; no relay).

## Comments

- Superseded by `.scratch/durable-sync/issues/07-lan-rediscovery-mdns.md` (and key proof in `04-key-proved-meet.md`). Do not implement here; work that ticket under durable-sync instead.
