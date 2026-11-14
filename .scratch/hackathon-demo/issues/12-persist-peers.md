# 12: Persist peers and catalog across restart

**What to build:** Restarting the agent keeps the device identity, trusted peers, peer URLs, and event log so the listener does not pair again and catalog history is not lost. Unblocks reliable auto-sync and discovery across sessions.

**Blocked by:** 01: Pair two devices

**Status:** ready-for-agent

- [ ] The device private key and public identity survive restart.
- [ ] Trusted peers and their peer URLs survive restart.
- [ ] The signed event log (and thus catalog) survives restart.
- [ ] After restart, sync with a previously paired peer works without pairing again.
- [ ] Audio bytes, metered flag, and in-progress reject timer remain local-only rules as today.
