# 03: Persist Peers + Locator hints; restart without re-pair

**What to build:** Trusted Peer identities and last-known Locator hints survive restart. After restart the listener can sync with a previously paired Peer without QR/short code once a Locator works (hint, paste, or existing meet path).

**Blocked by:** 02: Persist Identity + Event log; replay Catalog

**Status:** ready-for-human

- [x] Trusted Peer identities survive restart.
- [x] Last-known Locator hints survive restart and are non-authoritative (not Identity).
- [x] After restart, sync with a previously paired Peer works without pairing again once reachability is available.
- [x] Agent-level test: pair two Devices, restart both on their data dirs, meet again, Catalog sync without re-pair.

## Comments

- Implemented: trusted Peers continue via Event log `DEVICE_PAIRED` / `DEVICE_UNPAIRED` replay; last-known Locator hints live in `locator_hints.json` under explicit `data_dir` (loaded on boot, written from `remember_peer_url` / pairing URL / unpair revoke). After replay, stale hints for unpaired Peers are pruned. Persistence only when `data_dir` is set. Tests in `tests/test_persist_peers_and_locator_hints.py` (hints survive restart; unpair clears hints across restart; restart + meet without re-pair syncs Catalog).
