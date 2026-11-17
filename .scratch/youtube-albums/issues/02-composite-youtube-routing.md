# 02: CompositeSource routes YouTube hosts

**What to build:** Serve-mode artist add accepts `youtube.com` and `music.youtube.com` the same way as other platforms: CompositeSource dispatches those hosts to the YouTube Source so a pasted channel URL lists Album Releases end-to-end through the shared entry point. Unsupported hosts still fail with a clear allow-list error.

**Blocked by:** 01: YouTube Artist Source lists Album Releases

**Status:** ready-for-agent

- [ ] CompositeSource routes youtube.com and music.youtube.com list/fetch to the YouTube Source.
- [ ] Unsupported hosts still raise an actionable unsupported-host error (message includes YouTube in the allow list).
- [ ] Artist URL normalization for YouTube participates in add/refresh dedupe the same way Bandcamp normalization does.
- [ ] Routing tests cover YouTube hosts without hitting the network.
