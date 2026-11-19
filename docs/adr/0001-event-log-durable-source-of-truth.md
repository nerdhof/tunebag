# Event log is the durable Catalog source of truth

Catalog state must survive restart and converge across Peers without a server. We persist a signed append-only Event log plus local Device identity; on boot we rebuild Catalog by replaying the log (optionally accelerated by a disposable snapshot — [ADR-0008](0008-sqlite-durable-bag-and-incremental-pull.md)). Concurrent events use per-type deterministic merge (same event set ⇒ same Catalog); `created_at` and per-author `seq` are signed; LWW fields order by author time then `(device_id, seq, event.id)`; Playhead is the hybrid exception (within 2 minutes of author-time delta prefer higher position, else later author time). We rejected a separate durable Catalog authority, NTP-synchronized total ordering, and ledger/blockchain productization.

## Consequences

- Snapshot caches are allowed only if disposable; replay remains authoritative ([ADR-0008](0008-sqlite-durable-bag-and-incremental-pull.md)).
- Incremental sync uses per-author seq watermarks ([ADR-0008](0008-sqlite-durable-bag-and-incremental-pull.md)).
- `DEVICE_UNPAIRED` revokes future trust only; past applied events stay.
