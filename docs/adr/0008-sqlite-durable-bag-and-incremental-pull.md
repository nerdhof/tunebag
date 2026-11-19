# SQLite durable bag, disposable Catalog snapshot, incremental pull

JSONL Event log plus JSON identity/locator sidecars were awkward for crash safety and cold-start size. We store one SQLite file (`data_dir/tunebag.sqlite`) as the durable bag: signed Events, local Device identity, Locator hints, and a disposable Catalog snapshot blob + tip watermark. The Event log remains the Catalog source of truth ([ADR-0001](0001-event-log-durable-source-of-truth.md)); the snapshot is write-through after mutating journal sections and is discarded on projection-version mismatch or corruption (full replay + rewrite). `CatalogJournal.hold()` maps to one SQLite transaction so nested appends commit together. Peers pull with per-author seq watermarks via `POST /api/events/pull` (NDJSON); full export is `GET /api/events` as NDJSON. Legacy `events.jsonl` / `identity.json` / `locator_hints.json` auto-migrate into the bag and are renamed `*.migrated`.

**Considered:** keep JSONL; durable Catalog as SQL tables; single `after_event_id` cursor; Bloom/seen-id sync. Rejected — SoT stays the Event stream; Catalog-as-SQL and Bloom sync are out of scope; per-author `MAX(seq)` matches existing merge causality better than a global event id.

## Consequences

- Durable mode does not keep a full in-RAM Event list; export/pull stream from SQLite. In-memory EventLog remains for tests without `data_dir`.
- Bump `PROJECTION_VERSION` when apply/merge shape or snapshot codec fields change.
- Trust still lives only in the Event log (`DEVICE_PAIRED` / `DEVICE_UNPAIRED`); Locator hints stay non-authoritative.
