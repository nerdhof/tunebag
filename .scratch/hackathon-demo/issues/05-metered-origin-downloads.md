# 05: Hold origin downloads on a metered link

**What to build:** On a metered link the device keeps the mix in progress and one mix ahead per intent. The listener can top up one intent once, and a copy from a paired device still fills.

**Blocked by:** 04: Fill caches from the preferred device

**Status:** ready-for-agent

- [ ] A simulated switch marks the link metered, with no SIM required.
- [ ] While metered, origin downloads stay within the current mix, including one being resumed, plus one mix ahead per intent.
- [ ] Files already on the device stay when the link becomes metered.
- [ ] Fill now tops one intent up to that device's full hours once, then the cap applies again.
- [ ] A peer copy, including over USB, ignores the metered cap.
- [ ] Catalog sync still happens on a metered link.
