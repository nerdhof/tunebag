# 09: Refresh artists in the shared catalog

**What to build:** The listener re-lists known artists' own uploads. New mixes become catalog rows; existing platform ids and committed rejects are left alone. No audio is downloaded. Peers see the new rows after sync.

**Blocked by:** 02: Add artists to the shared catalog

**Status:** ready-for-agent

- [ ] One artist or all catalog artists can be refreshed in one step.
- [ ] Refresh reuses the same source `list_uploads` path as add.
- [ ] Uploads whose platform id is already in the catalog are skipped.
- [ ] Committed rejects are not resurrected as new catalog rows.
- [ ] The same min-duration default (20 minutes) and per-call override apply.
- [ ] Refresh creates no audio files.
- [ ] New rows appear on the paired device after sync.
