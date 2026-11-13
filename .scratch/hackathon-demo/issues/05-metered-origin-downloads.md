# 05: Hold origin downloads on a metered link

**What to build:** On a metered link the device keeps the mix in progress and one mix ahead per intent. The listener can top up one intent once, and a copy from a paired device still fills.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-human

- [x] A simulated switch marks the link metered, with no SIM required.
- [x] While metered, origin downloads stay within the current mix, including one being resumed, plus one mix ahead per intent.
- [x] Files already on the device stay when the link becomes metered.
- [x] Fill now tops one intent up to that device's full hours once, then the cap applies again.
- [x] A peer copy, including over USB, ignores the metered cap.
- [x] Catalog sync still happens on a metered link.

## Comments

- Implemented local `set_metered` / `set_current_mix` (not events), metered origin allowlist (current + one ahead per intent), `fill_now(intent_id)` one-shot override, peer copies always allowed. Demo UI: metered checkbox, Set current on cached files, Fill now per intent. Tests in `tests/test_metered_origin_downloads.py`.
