# 03: Persist Peers + Locator hints; restart without re-pair

**What to build:** Trusted Peer identities and last-known Locator hints survive restart. After restart the listener can sync with a previously paired Peer without QR/short code once a Locator works (hint, paste, or existing meet path).

**Blocked by:** 02: Persist Identity + Event log; replay Catalog

**Status:** ready-for-agent

- [ ] Trusted Peer identities survive restart.
- [ ] Last-known Locator hints survive restart and are non-authoritative (not Identity).
- [ ] After restart, sync with a previously paired Peer works without pairing again once reachability is available.
- [ ] Agent-level test: pair two Devices, restart both on their data dirs, meet again, Catalog sync without re-pair.
