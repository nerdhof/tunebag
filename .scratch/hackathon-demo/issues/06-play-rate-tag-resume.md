# 06: Play, rate, tag, and resume

**What to build:** The agent plays an intent through a local player on the laptop and on the phone. The browser is the remote control. The listener can rate, tag, mark played, and resume on the other device. The control page ends on the list of planned later features.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-agent

- [ ] The agent supervises a local player against files in its own cache. Closing the browser does not stop playback.
- [ ] On the phone the agent runs under Termux and keeps playing with the screen off while the agent process stays awake. A bundled APK is not part of this ticket.
- [ ] The same playback path is used on the laptop.
- [ ] Listening past 75% counts as played. Mark played counts as played without waiting. Stopping earlier leaves the mix in place in the sequence and on disk.
- [ ] The latest playhead syncs, and the other device resumes mid-mix when it has the file.
- [ ] Stars are 1 to 5 and stay separate from reject. One star leaves the mix eligible.
- [ ] Tags can be edited from the mix list and from the player. Suggestions are tags already in the catalog.
- [ ] A played mix goes to the back of the pool. Its file is deleted only once a replacement file is on the device.
- [ ] The player page closes by showing the planned later features, without implementing them.
