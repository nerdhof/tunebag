# 03: Album play, Playhead, Played, Reject cleanup

**What to build:** The Tunebag player plays an Album’s tracks in order as one listening item. Playhead is album-timeline seconds with resume across Devices. Played is 75% of summed duration (or explicit mark). Reject, Skip, Rate, and Tag apply to the whole Release; Reject removes the Album’s track directory after the undo window.

**Blocked by:** 02: Album Cache fill + intent folders

**Status:** ready-for-agent

- [ ] Playing an Album walks local track files in Catalog order.
- [ ] Playhead `position_seconds` is on the concatenated Album timeline; resume maps timeline → track via Catalog durations.
- [ ] Played triggers at 75% of summed Album duration (or explicit mark), same Release-scope rules as Mix.
- [ ] Last heard, Skip, Reject, Un-reject, Rate, and Tag apply to the whole Album only (no per-track Events).
- [ ] After Reject’s undo window, Album track Files are deleted on Devices the same way Mix blobs are.
- [ ] Existing Playhead merge rules still apply (single timeline number).
