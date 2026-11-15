# 02: Persist Identity + Event log; replay Catalog

**What to build:** Restarting the agent keeps Device identity and the Event log. Catalog comes back by replaying the log (no separate durable Catalog store). Local-only rules for Files, Metered, and Reject undo stay as today.

**Blocked by:** 01: Deterministic Catalog merge

**Status:** ready-for-agent

- [ ] Device identity (`device_id` + keypair) survives process restart in the same data directory.
- [ ] The signed Event log survives restart (JSONL append-only).
- [ ] On boot, Catalog is empty then rebuilt by replaying the Event log (artists and other projected state return).
- [ ] File bytes, Metered flag, and in-progress Reject undo timer remain local-only (not required in the Event log).
- [ ] Agent-level test: add Catalog state, construct a new agent on the same data dir, assert identity and Catalog without re-adding.
