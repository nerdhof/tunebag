# 06: Play, rate, tag, and resume

**What to build:** The agent plays an intent through a local player on the laptop and on the phone. The browser is the remote control. The listener can rate, tag, mark played, and resume on the other device. The control page ends on the list of planned later features.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-human

- [x] The agent supervises a local player against files in its own cache. Closing the browser does not stop playback.
- [x] On the phone the agent runs under Termux and keeps playing with the screen off while the agent process stays awake. A bundled APK is not part of this ticket.
- [x] The same playback path is used on the laptop.
- [x] Listening past 75% counts as played. Mark played counts as played without waiting. Stopping earlier leaves the mix in place in the sequence and on disk.
- [x] The latest playhead syncs, and the other device resumes mid-mix when it has the file.
- [x] Stars are 1 to 5 and stay separate from reject. One star leaves the mix eligible.
- [x] Tags can be edited from the mix list and from the player. Suggestions are tags already in the catalog.
- [x] A played mix goes to the back of the pool. Its file is deleted only once a replacement file is on the device.
- [x] The player page closes by showing the planned later features, without implementing them.

## Comments

- Agent-owned `play` / `stop` / `report_playhead` / `mark_played` (browser is remote control only; resume seeks from synced playhead). `PLAYHEAD` LWW + `PLAYED` events; sequence rebuild puts played mixes at the back of each star bucket; local file deleted only after another assigned mix is cached. `suggest_tags` and `later_features()` (from `docs/LATER.md`). Demo UI: player controls, rate/tag, closes on later panel. Tests in `tests/test_play_rate_tag_resume.py`. Reject undo stays issue 07. No bundled APK / Termux wakelock beyond the same agent path.
