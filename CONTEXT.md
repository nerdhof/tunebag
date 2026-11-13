# mixy domain context

Canonical vocabulary for the codebase. Align code and docs with these terms.

## Glossary

- **Mix** — one audio file treated as a single listening item (typically a DJ set). Budgets and “played” use its duration.
- **Album** (later) — Bandcamp-style release treated as one listening item; duration is the sum of its tracks.
- **Artist** — a source-platform creator whose own uploads are ingested into the catalog.
- **Catalog** — fully replicated metadata on every paired device (artists, mixes, tags, ratings, rejects, play history, intents, sequences, assignments).
- **Tag** — free-text label; suggestions prefer existing tags. Intent membership uses AND of required tags.
- **Stars** — rating 1–5. Separate from reject. Unrated mixes may still match a tagged intent.
- **Reject** — “never assign again”; after a 20s local undo window, bytes are deleted on every device.
- **Rest bucket** — unrated + 1★ + 2★ mixes when sampling by star distribution.
- **Intent** — shared plan: tag filter + star distribution. Devices attach hours and optional expiry.
- **Sequence** — seeded ordered list of mixes for one intent, length up to the largest device budget.
- **Assignment** — which device hours cover which prefix of the sequence (independent of whether audio is on disk).
- **File** — audio bytes present on a device (local cache state).
- **Cache** — the set of files a device currently holds for its assignments.
- **Peer** — a paired device reachable over LAN or USB, usable as a file source.
- **Metered** — network mode that caps origin downloads to current mix + one ahead per intent.
- **Fill now** — one-shot override that fills one intent to its full device budget on a metered link.
- **Playhead** — last known position in a mix; latest event wins across devices.
- **Played** — listened past 75% of duration, or explicitly marked played.
- **Event log** — signed append-only stream of catalog changes replicated between paired devices.

## Boundaries

- Catalog replicates. Audio does not, except as needed by assignments.
- Our player is the source of play / star / reject / tag / playhead signals in v1.
- External players may open intent folders; they do not write mixy signals in v1.
