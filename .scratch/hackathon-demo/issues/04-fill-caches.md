# 04: Fill caches from the preferred device

**What to build:** Assigned mixes become files in an intent folder on each device. The laptop downloads a shared mix and the phone receives that file from the laptop. The phone downloads only the mixes that are inside its own hours and not the laptop's.

**Blocked by:** 03: Share one sequence across device hours

**Status:** ready-for-human

- [x] Pairing priority puts the laptop ahead of the phone for origin downloads.
- [x] While the laptop is reachable, the phone does not download a shared mix from the source. It receives the file from the laptop once the laptop has it, without waiting for the laptop's extra hours to finish.
- [x] Mixes that are only inside the phone's hours are downloaded by the phone.
- [x] When the laptop is unreachable, the phone downloads its own hours from the source.
- [x] A copy from a paired device is preferred over the source.
- [x] Each intent on a device is a folder of that device's assigned files.
- [x] A file that was removed can be downloaded again from its source URL.

## Comments

- Implemented `DeviceAgent.fill_caches` with priority ∩ assignment ∩ reachability routing, peer `file_bytes` handoff, `disconnect`, blob store + intent folders under `data_dir`. Origin audio for SoundCloud/hearthis via yt-dlp (`fetch_audio_bytes`); agent tests use `FakeSource`. Tests in `tests/test_fill_caches.py` and `tests/test_source_fetch.py`. HTTP peer file transfer left for a later pass (plan: in-process peers only).
