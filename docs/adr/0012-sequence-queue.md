# Sequence Queue (Catalog front/back place)

Listeners browsing the Catalog need to put a matching Release at the **front** or **back** of one Intent’s Sequence without marking Played, Skipped, or Reject, and without switching playback. **Queue** removes the Release from that Sequence if it is already present, inserts it at the chosen end, then runs **Sequence fillup** (keep remaining order; append draws until the largest device budget). Peers converge via the resulting LWW `SEQUENCE_BUILT` / assignment Events — there is no durable Queue / pin Event.

**Considered:** sticky “pinned next” until played (separate Catalog state). Rejected as unnecessary product weight; a plain place + fillup matches Drop’s Event footprint and keeps merge simple.

**Consequences:** companion Catalog split control (↪ flipped = front, ↪ = back) opens a matching-Intent picker; agent validates filter match / non-rejected / not live current, places via `place_in_sequence`, then `provision_fillup` and async `request_fill`. Does not Switch to intent or start playback. Refuse Queue of the live current Release for that Intent (use Skip / transport instead).
