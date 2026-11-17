# 04: CONTEXT + about/planned describe YouTube Album Artist Source

**What to build:** Docs match shipped behavior: CONTEXT notes that Artist listing shape is platform-defined; about/planned (and LATER if needed) describe YouTube as an Artist Source that produces Album Releases from the releases tab under `Platform.YOUTUBE` — not a separate Music platform and not an undefined later primitive.

**Blocked by:** 02: CompositeSource routes YouTube hosts; 03: YouTube origin fetch with ejs, anonymous progressive audio

**Status:** ready-for-human

- [x] CONTEXT clarifies Artist ingest/listing is platform-defined (e.g. Mix uploads vs Album discography tabs) without implementation detail.
- [x] About/planned copy mentions YouTube Artist → Album Releases via the releases tab.
- [x] LATER (if it implied YouTube/Music vaguely) is aligned so this Source is not described as unimplemented future work once shipped.

## Comments

- CONTEXT Artist glossary notes platform-defined listing (SC/hearthis Mix vs Bandcamp/YouTube Album discography) and that YouTube Music is not a separate Catalog platform. About Artist concept + planned/LATER acknowledge the YouTube Artist → Album adapter (releases tab); planned leftover is anonymous auth cookies escape hatch. Stale Mix “albums later” copy removed.
