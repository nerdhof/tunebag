# 04: Fill caches from the preferred device

**What to build:** Assigned mixes become files in an intent folder on each device. The laptop downloads a shared mix and the phone receives that file from the laptop. The phone downloads only the mixes that are inside its own hours and not the laptop's.

**Blocked by:** 03: Share one sequence across device hours

**Status:** ready-for-agent

- [ ] Pairing priority puts the laptop ahead of the phone for origin downloads.
- [ ] While the laptop is reachable, the phone does not download a shared mix from the source. It receives the file from the laptop once the laptop has it, without waiting for the laptop's extra hours to finish.
- [ ] Mixes that are only inside the phone's hours are downloaded by the phone.
- [ ] When the laptop is unreachable, the phone downloads its own hours from the source.
- [ ] A copy from a paired device is preferred over the source.
- [ ] Each intent on a device is a folder of that device's assigned files.
- [ ] A file that was removed can be downloaded again from its source URL.
