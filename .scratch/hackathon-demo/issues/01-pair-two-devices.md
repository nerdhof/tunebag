# 01: Pair two devices

**What to build:** The listener starts an agent on the laptop and the same agent on the phone. Each device's browser opens that device's agent. The laptop shows a QR code and a short code, the phone pairs with either, and a catalog change made on one device shows up on the other.

**Blocked by:** None (can start immediately).

**Status:** ready-for-human

- [x] The CLI only starts the agent. Listening and pairing happen in the browser pointed at that device's agent.
- [x] The same serve command runs on the phone under Termux, and the phone's browser opens the agent on the phone.
- [x] The laptop shows a QR payload with the device name and public key, and a short code derived from that key works when the camera is not used.
- [x] After pairing, each device shows the other as a peer.
- [x] A catalog event written on one device is visible on the other after sync over the local network.
- [x] The private key stays on the device that created it.
