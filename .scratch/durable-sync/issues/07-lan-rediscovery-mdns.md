# 07: LAN rediscovery (mDNS)

**What to build:** Devices advertise and browse on the LAN via mDNS/DNS-SD. A trusted public key advertisement leads to key proof, Locator hint refresh, and sync. An unknown advertisement is only a pair candidate (QR/short code). Browse on start, network change, and slow periodic refresh when no trusted Peer has a live session.

**Blocked by:** 03: Persist Peers + Locator hints; restart without re-pair; 04: Key-proved meet

**Status:** ready-for-agent

- [ ] Agents advertise name, short code or key fingerprint, and enough to form a Locator; full public key is fetched before challenge.
- [ ] Browse runs on agent start, on network/interface change, and with slow periodic refresh while no trusted Peer has a live session.
- [ ] Trusted key + successful proof → refresh Locator hint and sync without QR/short code.
- [ ] Unknown key → pair candidate only; trust still requires QR or short code.
- [ ] Pasted Locator still works when discovery is unavailable; same-LAN only (no relay).
- [ ] Agent-level tests use an injected fake advertiser/browser (DeviceAgent seam); no dependency on live multicast in unit tests.
