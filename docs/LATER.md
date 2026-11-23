# Tunebag — later / next steps

Show these at the end of the hackathon demo (also on `/about#planned`). Not in the build.

## Planned features

- **Bandcamp track-level UX** — the Artist → Album adapter is in; seek-bar track marks + hover titles are in; later: per-track skip/reject, and titles while playing.
- **OR tag filters** on intents (e.g. `tribal OR relaxing`). Own sequence per filter. A release may appear in multiple intents; deletes wait until no remaining intent on that device wants the file.
- **Library import** from the laptop: match on-disk files to `~/.music-snd-downloaded.txt` (SoundCloud, hearthis.at, and Bandcamp ids), seed the laptop cache, mark archive ids with no remaining file as already seen. Artist refresh itself is hackathon issue 09 (re-list known artists; do not resurrect committed rejects or old deletes).
- **Profile import**: SoundCloud and hearthis.at follow lists.
- **Artist reposts** in addition to own uploads.
- **Search** across the catalog (and later across platforms) by tag, artist, title.
- **Suggested tags and ratings** from titles/metadata, later from audio analysis.
- **Peer cache file share**: decided — mTLS Peer meet + File HEAD/GET + fill-policy parity for HTTPS Peers ([ADR-0011](adr/0011-mtls-peer-meet-and-cache-file-share.md), `.scratch/peer-cache-file-share/`); USB file copy still later.
- ~~**Catalog snapshot cache**~~ — done: disposable SQLite Catalog snapshot + tip watermark; Event log replay remains authoritative ([ADR-0008](adr/0008-sqlite-durable-bag-and-incremental-pull.md)).
- ~~**Incremental Event log sync**~~ — done: per-author seq watermarks via `POST /api/events/pull` + NDJSON ([ADR-0008](adr/0008-sqlite-durable-bag-and-incremental-pull.md)).
- ~~**SQLite (or similar) persistence**~~ — done: one `tunebag.sqlite` durable bag for events, identity, hints, snapshot ([ADR-0008](adr/0008-sqlite-durable-bag-and-incremental-pull.md)).
- **Cross-network meet relay**: reach a paired Peer outside the LAN multicast domain without pasting a Locator (optional server/relay peer).
- **Web player as a paired peer** for ad-hoc listening from anywhere (same sync protocol).
- **Foobar (macOS) and Vanilla Music (Android)** opening intent folders as dumb consumers of files; signal capture stays in Tunebag until adapters exist.

## Explicitly out of the first cut

- Custom blockchain / ledger productization beyond a signed append-only event log between paired devices.
- Server-hosted catalog as a required dependency (optional later peer / relay is fine; see cross-network meet above).
- Splitting DJ mixes into chapter tracks.
