# 02: Un-reject + Catalog reject UX

**What to build:** The listener can Un-reject a Mix after a committed Reject so it may re-enter sequences again (Reject is no longer sticky — ADR-0003). Catalog browse gains a Rejected filter (default off), Reject with the same 20s local pending undo as the player, one-click Un-reject on rejected rows, and artist overview rejected Mix counts even when the filter is off. Un-reject does not restore File bytes; fill runs when the Mix is assigned again.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Un-reject clears Reject under LWW with Reject (signed author time then `(device_id, seq, event.id)`); an older Reject does not beat a newer Un-reject and vice versa
- [ ] After Un-reject, the Mix is eligible for sequences again; File bytes return only via normal Cache fill / peer / origin when assigned — no eager refetch on Un-reject
- [ ] Catalog Reject starts the same 20s local pending undo window as the player; undo during the window cancels before commit
- [ ] Catalog has a Rejected filter defaulting off; when on, rejected Mixes appear muted and can be Un-rejected in one click
- [ ] Artist overview summary includes a rejected Mix count even while the Rejected filter is off
- [ ] Behaviour is verified through DeviceAgent (sequences + reject/un-reject) and HTTP/UI contracts as needed; prior art: reject-with-undo tests
