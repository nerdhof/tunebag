# 03: Album play, Playhead, Played, Reject cleanup

**What to build:** The Tunebag player plays an Album’s tracks in order as one listening item. Playhead is album-timeline seconds with resume across Devices. Played is 75% of summed duration (or explicit mark). Reject, Skip, Rate, and Tag apply to the whole Release; Reject removes the Album’s track directory after the undo window.

**Blocked by:** 02: Album Cache fill + intent folders

**Status:** ready-for-human

- [x] Playing an Album walks local track files in Catalog order.
- [x] Playhead `position_seconds` is on the concatenated Album timeline; resume maps timeline → track via Catalog durations.
- [x] Played triggers at 75% of summed Album duration (or explicit mark), same Release-scope rules as Mix.
- [x] Last heard, Skip, Reject, Un-reject, Rate, and Tag apply to the whole Album only (no per-track Events).
- [x] After Reject’s undo window, Album track Files are deleted on Devices the same way Mix blobs are.
- [x] Existing Playhead merge rules still apply (single timeline number).

## Comments

- Album play maps timeline → track via `_album_timeline_location`; `play`/`seek` start the track file (not the cache dir). Track end auto-advances under `_supervise_playback` (start next file before `report_playhead` to avoid re-entrancy). Reject cleanup already rmtree’d album dirs. Tests in `tests/test_album_play_playhead_reject.py`.
