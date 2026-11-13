# 03: Share one sequence across device hours

**What to build:** The listener creates an intent and sets hours on the laptop and the phone. Both devices show one stored sequence, and the phone's hours are the opening stretch of the laptop's hours.

**Blocked by:** 02: Add artists to the shared catalog

**Status:** ready-for-agent

- [ ] An intent has a name, a tag filter, and star draw chances.
- [ ] Several tags match only mixes that have all of them. No tags match only untagged mixes.
- [ ] The default chances are 40% five-star, 30% four-star, 20% three-star, and 10% rest. Rest means unrated, one-star, and two-star.
- [ ] Rejected mixes are not candidates. An empty bucket is skipped and the other chances are rescaled.
- [ ] One seeded sequence is stored up to the largest device budget. The other device applies that sequence instead of drawing its own.
- [ ] Two hours on the phone and eight on the laptop show the same first stretch on both, plus the extra hours only on the laptop.
- [ ] A short stretch may be two five-star mixes.
- [ ] The sequence stops when the next mix would pass the largest budget. A single mix longer than the budget still fills an empty sequence.
