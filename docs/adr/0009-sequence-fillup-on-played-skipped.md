# Sequence fillup on Played, Skipped, and Reject

Played, sticky Skipped, and Reject used to drive a full Sequence rebuild, which reshuffled upcoming Releases. Listening queues should stay stable: Catalog maintenance **drops** the retired Release from the Sequence, **keeps the relative order** of remaining queued entries, and **appends** new draws (**Sequence fillup**) only until cumulative duration meets the largest device budget, then refreshes Assignments. Played and Skipped sit at the back of their star bucket for those new draws; Rejected stay ineligible. Immediate Skip still does not touch the Sequence (only the 5‑minute delay → sticky Skipped).

Full Sequence rebuild remains for Intent upsert/delete, Un-reject, artist delete, peer/sync underfill paths that need a redraw, and the companion **Regenerate sequence** verb.

**Considered:** full rebuild after every Played / Skipped / Reject (previous behavior). Rejected because it reorders the upcoming queue and breaks “what I already queued stays queued.”

**Consequences:** `fill_sequence` / `provision_fillup` keep remaining queued order; Catalog maintenance `MARK_PLAYED` / `SKIP_COMMIT` / `REJECT_COMMIT` call `fillup_all_sequences`, not `rebuild_all_sequences`.
