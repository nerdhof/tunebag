# 02: View-notice + refresh contract

**What to build:** Backend↔companion interactions match the reactivity rules in `docs/UI-ACTIONS.md`: after a user mutation, affected surfaces force-refresh; View notices refetch without force (editors preserved); local and peer Catalog changes invalidate the mapped sections; Activity and pairing session move onto View notices so their dedicated polls shrink or drop. Player transport may remain a lightweight poll. Sync is not “reload UI.”

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] Documented section taxonomy is implemented for Catalog-backed surfaces plus Activity and pairing session
- [x] User mutations use a shared “refresh affected surfaces” path with force where editors would otherwise skip rebuilds
- [x] View-notice refetches do not force-rebuild over focused editors
- [x] Peer Event ingest produces notices that update the companion without Sync-as-reload
- [x] Activity and pairing no longer depend on standalone 1s polls as the primary freshness mechanism
- [x] Tests lock local + peer notice→UI behaviour for the new sections

## Comments

- Extended `UIViewSection` with `activity` + `pairing_session`; `note()` and pairing-session transitions mark them (TTL expiry armed via timer).
- Companion: shared `refreshAffectedSurfaces({ force })`; notices use it without force; annotate mutations use `refreshAfterAnnotateMutation`. Dropped Activity 1s poll; pairing poll only while `pending_confirm`.
- Docs: `docs/UI-ACTIONS.md` taxonomy + reactivity. Tests: `tests/test_view_notice_refresh_contract.py` (+ existing notice suites tolerate auto-sync `activity` marks).
