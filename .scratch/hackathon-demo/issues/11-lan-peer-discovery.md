# 11: Discover mixy agents on the local network

**What to build:** A device can find other mixy agents on the LAN without the listener pasting a peer URL. Discovery surfaces candidates; pairing still requires explicit trust (QR, short code, or confirm).

**Blocked by:** 01: Pair two devices

**Status:** ready-for-agent

- [ ] Running agents advertise themselves on the local network.
- [ ] The UI lists discovered candidates with enough identity to choose one (name and/or short code).
- [ ] Discovery alone does not trust a peer; the listener still pairs explicitly.
- [ ] Pasted peer URL and QR pairing continue to work when discovery is unavailable.
