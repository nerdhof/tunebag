# 08: Expire one device's hours

**What to build:** The listener sets an expiry on one device's hours for an intent. At that time the device leaves the intent and drops files only it was holding. The other device keeps its hours and its files.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-human

- [x] Expiry is per device on an intent. The laptop can keep the intent after the phone's hours expire.
- [x] Expiry removes that device from the intent. It does not shrink the hours to a smaller standing budget.
- [x] Files held only by the expired device are deleted.
- [x] The mix currently playing stays until playback stops.
- [x] A file that another live assignment on the same device still wants stays.

## Comments

- Implemented `DeviceAgent.apply_expired_hours` (clock-driven; also from `sync`), optional `expires_at` on `create_intent` / `set_device_hours` / HTTP + device-hours UI. Expiry drops that device's `DeviceHours` and clears its assignment (`ASSIGNMENT_CLEARED`); `_prune_unassigned_files` deletes exclusive locals except the currently playing mix (reaped on `stop`) and mixes still wanted by another live assignment. Tests in `tests/test_expire_device_hours.py`.
