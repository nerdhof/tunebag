# Sequence Drop (upcoming queue edit)

Listeners need to remove an upcoming Release from one Intent’s Sequence without marking Played, Skipped, or Reject. **Drop** trims that Release from the current Sequence entries, then runs **Sequence fillup** (keep remaining order; append draws until the largest device budget). The trimmed Release stays eligible for this Intent: the same fillup or a later one may draw it again at a different position. Peers converge via the resulting LWW `SEQUENCE_BUILT` / assignment Events — there is no durable exclusion set or Drop Event.

**Considered:** intent-scoped sticky exclusion until Regenerate (blocked re-append). Rejected as unnecessary product weight; re-entry at another position is acceptable and simplifies Catalog merge.

**Consequences:** companion **Drop from sequence** on Playlog upcoming and Intent Shared sequence (confirm-click ⊖ → 💥); agent trims then `provision_fillup`, then async `request_fill`; no change to Played / Skipped / Reject / Regenerate semantics. Refuse Drop of the live current Release for that Intent (use Skip / transport instead).
