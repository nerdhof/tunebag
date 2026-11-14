# mixy — later / next steps

Show these at the end of the hackathon demo. Not in the build.

## Planned features

- **Bandcamp albums** as an alternative listening primitive. One album = one item; duration = sum of tracks; played = past 75% of the album as a whole.
- **OR tag filters** on intents (e.g. `tribal OR relaxing`). Own sequence per filter. A mix may appear in multiple intents; deletes wait until no remaining intent on that device wants the file.
- **Library import** from the laptop: match on-disk files to `~/.music-snd-downloaded.txt` (SoundCloud, hearthis.at, and Bandcamp ids), seed the laptop cache, mark archive ids with no remaining file as already seen. Artist refresh itself is hackathon issue 09 (re-list known artists; do not resurrect committed rejects or old deletes).
- **Profile import**: SoundCloud and hearthis.at follow lists.
- **Artist reposts** in addition to own uploads.
- **Search** across the catalog (and later across platforms) by tag, artist, title.
- **Suggested tags and stars** from titles/metadata, later from audio analysis.
- **Auto-sync** (hackathon issue 10): pull/push catalog events when a trusted peer is reachable and after local catalog writes, without pressing Sync.
- **LAN peer discovery** (hackathon issue 11): find mixy agents on the local network beyond a pasted peer URL or QR payload.
- **Persist peers** (hackathon issue 12): survive process restart — trusted peer identities, peer URLs, and event log so pairing is not required again (device private key already stays local).
- **Web player as a paired peer** for ad-hoc listening from anywhere (same sync protocol).
- **Foobar (macOS) and Vanilla Music (Android)** opening intent folders as dumb consumers of files; signal capture stays in mixy until adapters exist.

## Explicitly out of the first cut

- Custom blockchain / ledger productization beyond a signed append-only event log between paired devices.
- Server-hosted catalog as a required dependency (optional later peer is fine).
- Splitting DJ mixes into chapter tracks.
