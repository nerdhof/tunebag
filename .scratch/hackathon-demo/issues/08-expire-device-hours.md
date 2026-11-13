# 08: Expire one device's hours

**What to build:** The listener sets an expiry on one device's hours for an intent. At that time the device leaves the intent and drops files only it was holding. The other device keeps its hours and its files.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-agent

- [ ] Expiry is per device on an intent. The laptop can keep the intent after the phone's hours expire.
- [ ] Expiry removes that device from the intent. It does not shrink the hours to a smaller standing budget.
- [ ] Files held only by the expired device are deleted.
- [ ] The mix currently playing stays until playback stops.
- [ ] A file that another live assignment on the same device still wants stays.
