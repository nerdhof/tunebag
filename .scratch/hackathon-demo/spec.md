Status: ready-for-agent

# Hackathon demo

## Problem Statement

Listening to DJ mixes is a manual loop. Mixes are downloaded from SoundCloud and hearthis.at, kept or deleted by hand, and copied to a phone so they can be played with no network. There is no shared record of what was played, loved, or rejected, and no way to say "put these hours of this kind of mix on this device" and have both devices fill the same stretch of music. Ratings made in other players do not travel with the files.

## Solution

A listener runs Tunebag on the laptop and on the phone. Each device keeps the full catalog and only the audio its hours require. The listener adds artists, pairs the devices, and creates an intent: a tag filter and a star mix, with hours and an optional expiry per device. Both devices share one sequence. The phone's hours are the opening stretch of the laptop's hours. The laptop downloads that shared stretch and hands the files to the phone. The listener plays an intent in Tunebag's player, rates, tags, and rejects, and those signals sync when the devices can see each other. Played and rejected audio leaves the cache under the rules below. A metered link holds back new origin downloads. At the end of the demo, the listener sees the list of planned features that are not built yet.

## User Stories

1. As a listener, I want to add several artist URLs in one step, so that I can fill the catalog from more than one creator before I choose what to hear.
2. As a listener, I want each added artist to contribute only that artist's own uploads, so that reposts do not enter the catalog during the demo.
3. As a listener, I want those uploads recorded as catalog rows with title, duration, and source URL, so that I can plan a cache before any audio is downloaded.
4. As a listener, I want no audio downloaded at artist-add time, so that a long artist page does not fill the disk.
5. As a listener, I want to refresh artists already in the catalog so that new own-uploads become catalog rows without re-adding the artist URL, without resurrecting committed rejects, and without downloading audio.
6. As a listener, I want the laptop to show a QR code with its name and public key, so that the phone can pair by scanning it.
7. As a listener, I want a short code fallback when the camera fails, so that pairing still works.
8. As a listener, I want the phone to trust the laptop after a successful pair, so that later sync does not ask me to pair again.
9. As a listener, I want catalog changes to sync between paired devices on the local network, so that a tag or rating made on one device appears on the other.
10. As a listener, I want catalog sync to work on a metered link as well as on Wi-Fi, so that taste and plans travel even when audio does not.
11. As a listener, I want catalog changes to sync automatically when a paired peer is reachable, so that I do not have to press Sync after every change.
12. As a listener, I want to discover other Tunebag agents on the local network, so that I can find a peer without pasting its URL.
13. As a listener, I want previously paired peers and the catalog to survive restarting the agent, so that I do not have to pair again after a reboot.
14. As a listener, I want to create an intent with a name, a tag filter, and a star distribution, so that "what kind of mix" is separate from "how many hours on which device".
15. As a listener, I want an intent whose tags are several words to match only mixes that have all of those tags, so that a narrower plan does not fill with loosely related mixes.
16. As a listener, I want an intent with no tags to match only untagged mixes, so that exploratory listening has its own sequence.
17. As a listener, I want the star distribution to be the chance of drawing each bucket, so that a short budget and a long budget use the same rule.
18. As a listener, I want the default chances to be 30% five-star, 20% four-star, 10% three-star, 5% two-star, 5% one-star, and 30% unrated, so that I can start from the mix I described.
19. As a listener, I want unrated mixes to have their own chance bucket, so that unrated tagged mixes can still appear in a tagged intent.
20. As a listener, I want rejected mixes left out of every sequence, so that a mix I have rejected never comes back.
21. As a listener, I want an empty star bucket skipped and the other chances rescaled, so that a missing bucket does not stall the sequence.
22. As a listener, I want one seeded sequence per intent, long enough for the largest device budget, so that both devices are looking at the same order.
23. As a listener, I want that sequence stored when the intent or its hours change, so that a device which was offline applies the same list instead of drawing again.
24. As a listener, I want two hours on the phone and eight hours on the laptop to be the same first two hours, plus six more hours only on the laptop, so that the phone is a prefix of the laptop.
25. As a listener, I want a short prefix to be allowed to come out as two five-star mixes, so that probability is honest when the hours are small.
26. As a listener, I want the sequence to fill until it reaches at least the largest budget (including the mix that crosses it), so that I get at least the hours I asked for.
27. As a listener, I want a single mix that is longer than the whole budget to still be chosen when the sequence is empty, so that a plan is never silently empty when a mix exists.
28. As a listener, I want each device to have its own hours on an intent, so that the laptop can hold more audio than the phone.
29. As a listener, I want each device to have its own expiry on an intent, so that the phone can drop a plan while the laptop keeps it.
30. As a listener, I want expiry to remove that device from the intent rather than shrink it to a smaller standing budget, so that the end time means the plan is over on that device.
31. As a listener, I want files held only by the expired device to be deleted, so that a finished plan frees space.
32. As a listener, I want the mix that is currently playing to stay through expiry until playback stops, so that the player does not cut the audio.
33. As a listener, I want files another live assignment on that device still wants to stay, so that expiry of one intent does not punch a hole in another.
34. As a listener, I want the laptop, when it is reachable, to download a shared mix from the source and hand it to the phone, so that the phone does not download the same mix itself.
35. As a listener, I want the phone to receive each shared file as soon as the laptop has it, so that the phone does not wait for the laptop's extra hours to finish.
36. As a listener, I want mixes that are only inside the phone's hours to be downloaded by the phone, so that a larger phone plan is not stuck waiting for a laptop that did not ask for those mixes.
37. As a listener, I want the phone to download its own hours from the source when the laptop is unreachable, so that a commute still fills without the laptop online.
38. As a listener, I want pairing priority, with the laptop ahead of the phone, to decide who fetches from the source, so that a larger phone budget does not make the phone the downloader.
39. As a listener, I want a copy from a paired device to be preferred over the source, so that audio already on the laptop is reused.
40. As a listener, I want a deleted mix to be downloadable again from its source URL later, so that eviction does not permanently block a mix I might be assigned again.
41. As a listener, I want an unmetered link to fill each of my device's hours, so that a Wi-Fi session completes the cache.
42. As a listener, I want a metered link to keep the mix I am in, including one I am resuming, plus one mix ahead per intent, so that a mobile connection does not pull a multi-hour fill.
43. As a listener, I want audio already on the device to stay when I switch to a metered link, so that a cache I already paid for is not thrown away.
44. As a listener, I want Fill now to top up one intent to that device's full hours once, so that I can prepare a plan on mobile data without changing the standing cap.
45. As a listener, I want the metered cap to apply again after that one Fill now pass, so that the override does not become the new default.
46. As a listener, I want a peer copy, including over USB, to ignore the metered cap, so that local transfer does not spend mobile data.
47. As a listener, I want a simulated metered switch in the demo, so that I can show the cap without a SIM.
48. As a listener, I want each intent materialized as a folder of the mixes assigned to this device, so that I can see a plan as a set of files.
49. As a listener, I want to play an intent in Tunebag's player, so that play, stars, reject, tags, and playhead are recorded by Tunebag.
50. As a listener, I want listening past 75% of a mix to count as played, so that finishing a set updates the catalog without an extra click.
51. As a listener, I want an explicit Mark played control, so that the demo can advance without sitting through a long mix.
52. As a listener, I want stopping before 75% to leave the mix in place in the sequence and on disk, so that a pause is not treated as finishing.
53. As a listener, I want the latest playhead to sync, so that the other device can resume the same mix mid-way when it has the file.
54. As a listener, I want to set a star rating from 1 to 5, so that preference is separate from throwing a mix away.
55. As a listener, I want one star to keep a mix eligible, so that a low rating is not a delete.
56. As a listener, I want to edit tags from the mix list and from the player, so that I can classify a mix where I am already listening.
57. As a listener, I want tag entry to suggest tags that already exist in the catalog, so that I reuse labels instead of inventing spellings.
58. As a listener, I want a played mix to go to the back of the pool, so that it can be drawn again later instead of being banned.
59. As a listener, I want a played mix's file deleted only once a replacement file is on the device, so that finishing a mix does not empty the cache before the next one arrives.
60. As a listener, I want reject to wait 20 seconds on the device where I pressed it, so that I can undo a mis-tap.
61. As a listener, I want nothing about that reject synced during the 20 seconds, so that the other device does not delete the file before I can undo.
62. As a listener, I want undo during those 20 seconds to cancel the reject, so that the mix stays eligible.
63. As a listener, I want a committed reject to delete the file on every device that has it, so that a rejected mix leaves the whole paired set.
64. As a listener, I want a committed reject to keep the mix out of future sequences, so that deletion of the bytes is not the only memory of the decision.
65. As a listener, I want the demo player to show the planned-later list at the end, so that albums, OR filters, and the other follow-ups are visible without being built.
66. As a listener, I want the phone demo to be the same player pointed at a second device agent, so that pairing and sync are real even when both agents run on the laptop.

## Implementation Decisions

- One device agent per device is the interface the web player and the CLI call. Tests construct two agents and use them as paired peers. HTTP is the demo transport of that same agent, not a second behavior.
- The catalog is rebuilt by replaying a signed append-only event log. Audio bytes, the simulated metered flag, the in-progress reject timer, and the device private key stay local and are not events.
- A sequence is an event, written when the intent or its device hours change. Assignments are the per-device prefixes of that stored sequence, cut by duration. A device that syncs the events does not draw its own sequence.
- Star draw chances are always probabilities, at every budget. The shared sequence is produced with one seed and fills until its duration is at least the largest device budget, including the mix that crosses it. Smaller hours take a duration prefix of that sequence. An empty bucket is skipped and the remaining chances are rescaled. Rejected mixes are not candidates.
- The distribution shape is six buckets named five, four, three, two, one, and unrated, required to sum to 1, defaulting to 0.3, 0.2, 0.1, 0.05, 0.05, and 0.3.
- Pairing exchanges a device name and an Ed25519 public key. The laptop shows the QR payload. The short code is derived from that key. The laptop's fetch priority is ahead of the phone's.
- The hackathon demo uses auto-sync when a trusted peer is reachable (Sync remains a manual override), explicit peer URL or QR (no LAN discovery), and in-memory peers/event log (restart clears pairing). LAN discovery and persistence are issues 11–12.
- Reachability is a heartbeat. For each assigned mix, the highest-priority reachable device whose own hours include that mix downloads it from the source URL. Other devices take the file from that peer. If the preferred device is unreachable, the device that has the mix in its hours downloads it.
- Artist ingest lists own uploads and writes catalog rows only. Download of audio uses the source URL directly and does not consult the existing download archive, so a mix removed from disk can be fetched again. SoundCloud and hearthis.at URLs are resolved by a Source adapter selected by host. Add applies a configurable minimum duration (default 20 minutes) before writing mix rows.
- Artist refresh (issue 09) reuses the same `list_uploads` path. It is idempotent on platform ids, never resurrects a committed reject, applies the same min-duration rule, and writes catalog rows only (no audio).
- Unmetered fills the device's assignments. Metered origin fetches are limited to the current mix (including a resumed one) and one mix ahead per intent. Files already present stay. Fill now is one pass over one intent's full hours, then the cap returns. Peer and USB copies are treated as unmetered.
- Intent folders are directories of links into the local blob store, one folder per intent on that device. A played file is removed after the replacement blob is local. A committed reject removes the blob on each device that has it. Expiry removes blobs that no remaining local assignment wants, except the mix currently playing.
- Played is position at or past 75% of duration, or Mark played. A playhead event is last-write-wins by timestamp. Tags are free text, normalized, and suggestions are the existing catalog tags with that prefix.
- The demo process model is two agents. The phone UI is the web player served by the phone agent. A simulated control sets the metered flag. The closing screen lists the later features.
- The existing in-memory catalog, seeded draw, budget prefix helper, reject timer, key generation, and player shell stay. The agent becomes the place those pieces are used. The helper that currently returns the full sequence for every device is not the assignment rule.

## Testing Decisions

- A good test drives a device agent the way the listener does and asserts catalog, assignments, files, and what the other agent can see. It does not call the draw function, the event log, or HTTP routes directly.
- The only seam is the device agent. Tests build two agents. A fake source lists uploads and returns bytes. A fake clock advances the reject window and expiry. The peer of each agent is the other agent.
- There are no existing tests in the repo. New tests should cover the demo stories that are easy to get wrong: shared prefix, no origin fetch of a shared mix while the preferred peer is reachable, phone-only mixes fetched by the phone, metered cap leaving surplus in place, Fill now then the cap returning, reject invisible to the peer until 20 seconds, played file remaining until the replacement is local, and expiry deleting only exclusive files while a current mix keeps playing.
- Live network fetches and a real QR camera are outside the agent tests. The web player can be checked by calling the agent, not by asserting markup.

## Out of Scope

- Bandcamp albums as one listening item.
- Intent filters with OR.
- Importing the laptop library from on-disk files plus the existing download archive.
- Importing SoundCloud or hearthis.at follow lists.
- Artist reposts.
- Search.
- Suggested tags and stars from titles, metadata, or audio.
- A web player as a remote paired peer.
- Foobar or Vanilla Music reading or writing signals.
- A server, a blockchain, and splitting a mix into tracks.
- Publishing the GitHub remote. That is repo setup, not this demo.
- LAN peer discovery (issue 11).
- Persisting peers, peer URLs, and the event log across agent restart (issue 12).

## Further Notes

- Vocabulary is the glossary in the domain context: mix, catalog, sequence, assignment, file, intent, stars, reject, star distribution, tag, peer, metered, Fill now, playhead, played, event log.
- The listener's `snd` tool records downloads in an archive that refuses a URL after the first fetch. Mixy must not use that archive as a gate.
- The hackathon close shows the out-of-scope list. It does not implement it.
