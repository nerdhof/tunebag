# 05: Switch to intent, Regenerate sequence, drop global Fill

**What to build:** Intent rows use **Switch to intent** (select that Intent as Player’s current Intent and start/continue playback; pause when that Intent is already playing). Sequence rebuild is labeled **Regenerate sequence**, distinct from Catalog **Refresh artist(s)**. Cache UI no longer offers global Fill; Metered autofill and per-Intent **Fill now** remain. Freshness after these actions uses the refresh/notice contract from ticket 02.

**Blocked by:** 02: View-notice + refresh contract

**Status:** ready-for-agent

- [ ] Intent row control is Switch to intent: selects Intent and plays; pauses when that Intent is already playing
- [ ] Sequence rebuild control/tip says Regenerate sequence (not Refresh)
- [ ] Cache UI has no global Fill affordance; Fill now on Intents and Metered behaviour remain
- [ ] After Switch / Regenerate / Fill now, Player and related surfaces update via the shared refresh/notice path
- [ ] Tips and tests match UI-ACTIONS verb glossary for these controls
