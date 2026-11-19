# 05: Switch to intent, Regenerate sequence, drop global Fill

**What to build:** Intent rows use **Switch to intent** (select that Intent as Player’s current Intent and start/continue playback; pause when that Intent is already playing). Sequence rebuild is labeled **Regenerate sequence**, distinct from Catalog **Refresh artist(s)**. Cache UI no longer offers global Fill; Metered autofill and per-Intent **Fill now** remain. Freshness after these actions uses the refresh/notice contract from ticket 02.

**Blocked by:** 02: View-notice + refresh contract

**Status:** resolved

- [x] Intent row control is Switch to intent: selects Intent and plays; pauses when that Intent is already playing
- [x] Sequence rebuild control/tip says Regenerate sequence (not Refresh)
- [x] Cache UI has no global Fill affordance; Fill now on Intents and Metered behaviour remain
- [x] After Switch / Regenerate / Fill now, Player and related surfaces update via the shared refresh/notice path
- [x] Tips and tests match UI-ACTIONS verb glossary for these controls

## Comments

- Intent row: tip/aria **Switch to intent** (▶) / **Pause** when that Intent is playing; same pause-or-playIntent behaviour. Sequence control tip **Regenerate sequence**; per-Intent **Fill now**.
- Cache: removed `#fill-btn` / `/api/fill` UI call (API may remain). Empty-cache copy and section tips point at Fill now. Intents/Cache ⓘ tips use glossary verbs.
- Freshness: `refreshAfterIntentPlaybackMutation` for Switch/Pause; Regenerate and Fill now call `refreshAffectedSurfaces(..., { force: true })`.
- Contract: `tests/test_intent_verbs_drop_global_fill.py`. Gaps note in `docs/UI-ACTIONS.md` updated.
