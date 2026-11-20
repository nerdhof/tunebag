# Reject confirm-click and 5‑minute soft window

Reject used a 20s device-local undo buffer before appending `MIX_REJECTED`, then deleted File bytes when that window ended. That fought the confirm-click pattern used elsewhere, hid “just rejected” rows behind filters, and made Un-reject during the old window a different verb (undo) than Un-reject after commit.

We replace the undo buffer with **confirm-click → Reject Event immediately**. Soft vs Hard Rejected are **UI visibility only** (not Event types): for 5 minutes after Reject Event author time the Release stays in default Catalog browse (muted); afterward it is filter-only. Playlog shows Soft as ✕ + size and Hard as ✕ while the row remains in window. **File byte deletion waits until that soft window ends**, so Un-reject during Soft can still find local bytes; after Hard, Un-reject still does not restore bytes ([ADR-0003](0003-unreject-clears-reject.md)). Separately, the Playlog **previous-File cushion** keeps the immediate previous Release’s bytes for the same 5 minutes so ◀ works; that cushion is not Soft Reject. Player offers Reject only; Catalog and Playlog offer Reject or Un-reject depending on state.

**Considered:** keep the 20s undo buffer; treat soft as pre-commit pending without an Event. Rejected because peers would not see Reject during pending, and undo duplicated Un-reject.

**Consequences:** Catalog/API must expose Reject author time (or equivalent) for the soft window; remove RejectBuffer undo UX and `reject_pending_until` as the product model; update companion UI and tests in a later pass. Older `.scratch/` / demo notes that describe 20s undo are historical.
