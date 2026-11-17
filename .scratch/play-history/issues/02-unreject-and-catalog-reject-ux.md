# 02: Un-reject + Catalog reject UX

**What to build:** The listener can Un-reject a Mix after a committed Reject so it may re-enter sequences again (Reject is no longer sticky — ADR-0003). Catalog browse gains a Rejected filter (default off), Reject with the same 20s local pending undo as the player, one-click Un-reject on rejected rows, and artist overview rejected Mix counts even when the filter is off. Un-reject does not restore File bytes; fill runs when the Mix is assigned again.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [x] Un-reject clears Reject under LWW with Reject (signed author time then `(device_id, seq, event.id)`); an older Reject does not beat a newer Un-reject and vice versa
- [x] After Un-reject, the Mix is eligible for sequences again; File bytes return only via normal Cache fill / peer / origin when assigned — no eager refetch on Un-reject
- [x] Catalog Reject starts the same 20s local pending undo window as the player; undo during the window cancels before commit
- [x] Catalog has a Rejected filter defaulting off; when on, rejected Mixes appear muted and can be Un-rejected in one click
- [x] Artist overview summary includes reject/played/rated rollup rates (over all mixes) even while the Rejected filter is off
- [x] Behaviour is verified through DeviceAgent (sequences + reject/un-reject) and HTTP/UI contracts as needed; prior art: reject-with-undo tests

## Comments

- Implemented: `EventType.MIX_UNREJECTED` + DeviceAgent `un_reject_mix`; Reject/Un-reject share `_merge_beats(("reject", mix_id), …)` (ADR-0003). HTTP `POST /api/mixes/{id}/un-reject`; `/api/artists` exposes `mixes` + `rejected_mixes`. Catalog UI: Rejected filter chip (default off), muted `.mix-rejected` rows, reject/undo/un-reject on mix rows; artist fold line shows `avg★rated% #tagged% ✕reject% ▶played%` from all mixes (absolute `N rejected` replaced by rates). Tests in `tests/test_unreject_and_catalog_reject_ux.py`.
