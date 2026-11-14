# 07: Reject with undo

**What to build:** The listener can reject a mix and undo that choice for 20 seconds on the same device. After that, every paired device deletes the file and the mix never returns to a sequence.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-human

- [x] Reject starts a 20 second undo window on the device where it was pressed.
- [x] During that window nothing about the reject is synced.
- [x] Undo during the window cancels the reject and the mix stays eligible.
- [x] When the window ends, every device that has the file deletes it.
- [x] A committed reject keeps the mix out of future sequences.

## Comments

- Wired `RejectBuffer` into `DeviceAgent` with injectable `clock`. `reject_mix` starts a local pending window (no event); `undo_reject` cancels; `commit_pending_rejects` emits `MIX_REJECTED`, deletes the local blob, rebuilds sequences, and fills. `sync()` and status paths flush ready commits first. Peers delete on ingest. HTTP: `POST /api/mixes/{id}/reject` and `undo-reject`; player Reject/Undo UI with `reject_pending_until`. Tests in `tests/test_reject_with_undo.py`.
