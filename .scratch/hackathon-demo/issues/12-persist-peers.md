# 12: Persist peers and catalog across restart

**What to build:** Restarting the agent keeps Device identity, trusted Peer identities, last-known Locator hints, and the Event log so the listener does not pair again and Catalog history is not lost. Catalog is rebuilt by replaying the Event log. See ADR 0001 / 0002 and `CONTEXT.md`.

**Blocked by:** 01: Pair two devices

**Status:** wontfix

- [ ] Device identity (`device_id` + keypair) survives restart.
- [ ] Trusted Peer identities and last-known Locator hints survive restart (hints are not Identity; sync still needs key proof when meeting).
- [ ] The signed Event log survives restart; Catalog is rebuilt by replay (not a separate durable Catalog store).
- [ ] After restart, sync with a previously paired Peer works without pairing again once a Locator is proven (hint and/or discovery).
- [ ] File bytes, Metered flag, and in-progress Reject undo timer remain local-only rules as today.

## Comments

- Superseded by `.scratch/durable-sync/issues/02-persist-identity-and-event-log.md` and `03-persist-peers-and-locator-hints.md`. Do not implement here; work those tickets under durable-sync instead.
