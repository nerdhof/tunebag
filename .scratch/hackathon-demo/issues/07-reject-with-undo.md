# 07: Reject with undo

**What to build:** The listener can reject a mix and undo that choice for 20 seconds on the same device. After that, every paired device deletes the file and the mix never returns to a sequence.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-agent

- [ ] Reject starts a 20 second undo window on the device where it was pressed.
- [ ] During that window nothing about the reject is synced.
- [ ] Undo during the window cancels the reject and the mix stays eligible.
- [ ] When the window ends, every device that has the file deletes it.
- [ ] A committed reject keeps the mix out of future sequences.
