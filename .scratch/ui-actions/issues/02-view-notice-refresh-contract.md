# 02: View-notice + refresh contract

**What to build:** Backend↔companion interactions match the reactivity rules in `docs/UI-ACTIONS.md`: after a user mutation, affected surfaces force-refresh; View notices refetch without force (editors preserved); local and peer Catalog changes invalidate the mapped sections; Activity and pairing session move onto View notices so their dedicated polls shrink or drop. Player transport may remain a lightweight poll. Sync is not “reload UI.”

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] Documented section taxonomy is implemented for Catalog-backed surfaces plus Activity and pairing session
- [ ] User mutations use a shared “refresh affected surfaces” path with force where editors would otherwise skip rebuilds
- [ ] View-notice refetches do not force-rebuild over focused editors
- [ ] Peer Event ingest produces notices that update the companion without Sync-as-reload
- [ ] Activity and pairing no longer depend on standalone 1s polls as the primary freshness mechanism
- [ ] Tests lock local + peer notice→UI behaviour for the new sections
