# Tunebag — later / next steps

Show these at the end of the hackathon demo (also on `/about#planned`). Not in the build.

## Planned features

- **Bandcamp albums** as an alternative listening primitive. One album = one item; duration = sum of tracks; played = past 75% of the album as a whole.
- **OR tag filters** on intents (e.g. `tribal OR relaxing`). Own sequence per filter. A mix may appear in multiple intents; deletes wait until no remaining intent on that device wants the file.
- **Library import** from the laptop: match on-disk files to `~/.music-snd-downloaded.txt` (SoundCloud, hearthis.at, and Bandcamp ids), seed the laptop cache, mark archive ids with no remaining file as already seen. Artist refresh itself is hackathon issue 09 (re-list known artists; do not resurrect committed rejects or old deletes).
- **Profile import**: SoundCloud and hearthis.at follow lists.
- **Artist reposts** in addition to own uploads.
- **Search** across the catalog (and later across platforms) by tag, artist, title.
- **Suggested tags and ratings** from titles/metadata, later from audio analysis.
- **Peer cache file share**: copy assigned Mix bytes from a reachable Peer’s Cache over HTTP (and USB when present) before origin download; honor fetch priority / metered rules (peer/USB = unmetered). Closes the gap between in-process demo copy and real multi-process devices.
- **Catalog snapshot cache**: disposable on-disk Catalog projection for faster boot; Event log replay remains authoritative if they disagree.
- **Incremental Event log sync**: per-Peer cursors / `since` instead of full-log pull once logs get large.
- **SQLite (or similar) persistence**: if JSONL Event log + sidecar JSON becomes awkward for size, query, or crash safety.
- **Cross-network meet relay**: reach a paired Peer outside the LAN multicast domain without pasting a Locator (optional server/relay peer).
- **Web player as a paired peer** for ad-hoc listening from anywhere (same sync protocol).
- **Foobar (macOS) and Vanilla Music (Android)** opening intent folders as dumb consumers of files; signal capture stays in Tunebag until adapters exist.

## Explicitly out of the first cut

- Custom blockchain / ledger productization beyond a signed append-only event log between paired devices.
- Server-hosted catalog as a required dependency (optional later peer / relay is fine; see cross-network meet above).
- Splitting DJ mixes into chapter tracks.
