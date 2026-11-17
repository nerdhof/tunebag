# Tunebag — hackathon demo script

Target: **3–5 minutes** (aim ~4). Tagline: *Music packed for every device.*

## Prep

- Laptop and phone UIs ready; same LAN (or Locator ready).
- Artists to add known: SoundCloud **pingipung**, hearthis **tasmo**.
- One Intent already usable (or create live — know the clicks).
- Don’t discover pairing friction live; rehearse PIN once with a timer.

## Script

### Hook (~40s)

I listen to music from different sources — often mixes on hearthis.at or SoundCloud, sometimes albums from Bandcamp. Not on one device: I move between locations and devices. Managing what I’m enjoying across platforms and devices gets cumbersome. I also prefer offline caches over streaming — for example, to be ready for a bad network on the train through rural Brandenburg.

This is where Tunebag comes in: a music player that helps you **pack the music you want across devices and locations** — offline-first.

Let’s dive in.

### Idea (~40s)

Open **About** → context graph. Click through quickly; focus on **Intent** as the new basic concept.

Spoken definition: an Intent is a listening **plan** — *what* kind of music (tags / ratings), *how many hours*, *on which device*. The full Catalog syncs to every paired device; each device only caches the audio its hours require.

### Single device (~60s)

Main UI:

1. Add artists — SoundCloud (**pingipung**) and hearthis (**tasmo**).
2. Show the Intent **sequence** building.
3. Show the **cache** filling for this device’s hours.

Say *why* it’s filling: this device wants N hours of this Intent — so Tunebag packs that audio onto disk.

### Multi-device (~90s)

Real value: a second device — e.g. the phone.

1. Phone UI → peers → ⌕ (Show PIN) → copy.
2. Laptop UI → peers → select phone → paste PIN → + (Join).
3. Confirm matching codes on both.

Show the Catalog already there and the phone **cache** starting to fill for its assignment.

Then **one sync beat** (most visceral):

- Rate & tag the current song on the phone via **history**.
- Show rating/tags reflected on the laptop.

Close the offline loop: *now the phone is packed for the train — even with no network.*

**If time allows:**

- Change the laptop’s assignment from the phone → laptop UI reflects it.
- Create another Intent on the laptop, assigned to the phone, with an expire → phone cache updates.

### Close (~30s)

About → scroll to **Planned features**. These are next steps to make Tunebag usable long-term beyond the hackathon. Source and more: [github.com/wabu/tunebag](https://github.com/wabu/tunebag).

## Cut order if over time

1. Second Intent with expire  
2. Assignment flip  
3. Deep graph walk (Intent + one neighbor is enough)

Protect: Intent one-liner + pairing + phone rating → laptop sync.

## Notes

- Prefer **device / peer** over “client” when speaking (matches domain language).
- Pairing + three sync stories will blow past 5 minutes — keep one sync story as the default.
