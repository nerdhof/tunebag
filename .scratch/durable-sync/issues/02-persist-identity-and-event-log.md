# 02: Persist Identity + Event log; replay Catalog

**What to build:** Restarting the agent keeps Device identity and the Event log. Catalog comes back by replaying the log (no separate durable Catalog store). Local-only rules for Files, Metered, and Reject undo stay as today.

**Blocked by:** 01: Deterministic Catalog merge

**Status:** ready-for-human

- [x] Device identity (`device_id` + keypair) survives process restart in the same data directory.
- [x] The signed Event log survives restart (JSONL append-only).
- [x] On boot, Catalog is empty then rebuilt by replaying the Event log (artists and other projected state return).
- [x] File bytes, Metered flag, and in-progress Reject undo timer remain local-only (not required in the Event log).
- [x] Agent-level test: add Catalog state, construct a new agent on the same data dir, assert identity and Catalog without re-adding.

## Comments

- Implemented: `identity.json` + `events.jsonl` under explicit `data_dir`; cold start empties Catalog and replays via `_apply`. CLI `serve` passes `~/.mixy`. Persistence only when `data_dir` is set so in-process multi-agent tests do not share one identity. Tests in `tests/test_persist_identity_and_event_log.py`.
