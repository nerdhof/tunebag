# mixy — locked hackathon plan

Shared understanding locked 2026-11-13. Do not reopen unless product decisions change.

## Domain

| Term | Meaning |
| --- | --- |
| Mix | One audio file (usually a DJ set). Duration of the file is the budget unit. |
| Catalog | Artists, mixes, tags, stars, rejects, play history, intents, sequences, assignments. Fully replicated on every paired device. |
| Sequence | Seeded ordered list of mixes for one intent, built from the tag filter and star distribution. Shared across devices. |
| Assignment | Which device hours cover which prefix of the sequence. Separate from whether the file is on disk. |
| File | Audio bytes present on a device. Local only. |
| Intent | Tag filter + star distribution. Device hours and expiry hang off the intent. |
| Reject | Separate from stars. After a 20s local undo window, every device deletes the file and the mix never re-enters a sequence. |

Stars are 1–5. Unrated mixes may still enter a tagged sequence. The star distribution is six draw chances, 5★ through 1★ plus unrated, defaulting to 0.3 / 0.2 / 0.1 / 0.05 / 0.05 / 0.3.

## Rules

### Library

- No device keeps the full audio archive.
- Adding an artist records that artist’s **own uploads** as catalog rows. Audio waits until assignment.
- Peer/USB copy first; otherwise re-download from the source URL.
- Do not use `~/.music-snd-downloaded.txt` as a download gate. Eviction must allow re-download.

### Intents

- Tags on an intent mean AND (mix has all of them). Empty filter = untagged (exploratory).
- Star distribution is always a draw probability, at any budget.
- One seeded sequence fills until its duration is at least the largest device budget, and may include the mix that crosses that budget. Smaller budgets take the prefix (2h phone ≡ first 2h of 8h laptop).
- Empty bucket → skip and rescale remaining probabilities.
- A short stretch may be two 5★ mixes.
- Expiry is per device on the intent. Expiring removes that device from the plan; other devices keep their hours. Exclusive files are deleted except the currently playing mix.

### Fetch priority

- Pairing sets device priority. Laptop ahead of phone by default.
- Highest-priority reachable device that has the mix in its hours downloads from source, then hands the file to peers.
- Phone does not download the same mix from origin while the laptop is reachable.
- Mixes only the phone asked for stay the phone’s job.

### Metered

- OS metered flag (demo: simulated switch).
- Unmetered: fill device hours.
- Metered: current mix (including resume) + one ahead per intent. Surplus already downloaded stays.
- Fill now: one shot to full budget for one intent, then return to the cap.
- Peer/USB copies count as unmetered.
- Catalog sync on any network.

### Player (ours only for signals)

- Played = past 75% or explicit Mark played.
- Playhead syncs; latest wins.
- Stars and reject are separate.
- Tags editable from list and player; suggest existing tags.
- Played → back of pool; delete bytes once replacement is local.
- Reject → 20s local undo (no sync yet); then tombstone + delete everywhere.

### Pairing

- QR on laptop (device name + public key); short code fallback.
- Signed append-only event log over LAN / USB. No server in the hackathon.
- Web player later = another paired peer.

## Demo script

1. Add several artist URLs → catalog rows (no audio yet).
2. Pair phone ↔ laptop via QR (short code fallback).
3. Create an intent; set hours on both devices; set expiry on one.
4. Watch caches fill (laptop fetches shared stretch; phone receives it).
5. Flip metered → current + one ahead; Fill now tops up one intent.
6. Play in our player: star / reject / tag / playhead; watch sync.
7. Played and rejected files leave per rules above; expired device drops exclusive files.
8. Close with later list ([LATER.md](LATER.md)).
