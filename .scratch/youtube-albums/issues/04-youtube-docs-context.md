# 04: CONTEXT + about/planned describe YouTube Album Artist Source

**What to build:** Docs match shipped behavior: CONTEXT notes that Artist listing shape is platform-defined; about/planned (and LATER if needed) describe YouTube as an Artist Source that produces Album Releases from the releases tab under `Platform.YOUTUBE` — not a separate Music platform and not an undefined later primitive.

**Blocked by:** 02: CompositeSource routes YouTube hosts; 03: YouTube origin fetch with ejs, anonymous progressive audio

**Status:** ready-for-agent

- [ ] CONTEXT clarifies Artist ingest/listing is platform-defined (e.g. Mix uploads vs Album discography tabs) without implementation detail.
- [ ] About/planned copy mentions YouTube Artist → Album Releases via the releases tab.
- [ ] LATER (if it implied YouTube/Music vaguely) is aligned so this Source is not described as unimplemented future work once shipped.
