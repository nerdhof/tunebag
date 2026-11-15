# Event log is the durable Catalog source of truth

Catalog state must survive restart and converge across Peers without a server. We persist a signed append-only Event log (JSONL) plus a small sidecar for Device identity and trust; on boot we rebuild Catalog by replaying the log. Concurrent events use per-type deterministic merge (same event set ⇒ same Catalog); `created_at` and per-author `seq` are signed; LWW fields order by author time then `(device_id, seq, event.id)`; Playhead is the hybrid exception (within 2 minutes of author-time delta prefer higher position, else later author time). We rejected a separate durable Catalog store, NTP-synchronized total ordering, and ledger/blockchain productization.

## Consequences

- Snapshot caches are allowed later only if disposable; replay remains authoritative.
- Full-log sync is fine until size hurts; incremental cursors come after.
- `DEVICE_UNPAIRED` revokes future trust only; past applied events stay.
