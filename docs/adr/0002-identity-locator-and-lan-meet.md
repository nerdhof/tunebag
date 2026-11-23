# Identity vs Locator, key proof, and LAN meet

Network addresses change across home/work/hackspace, so Identity (`device_id` + keypair) must not be a URL. Locators are ephemeral reachability hints (optionally last-known on disk); they never grant trust. Before Event log sync, the process at a Locator must pass a private-key challenge–response; the proof lasts for the live session only. An ephemeral pairing session (PIN + dual SAS confirm; optional QR) establishes trust (first pair or re-pair after unpair) — see ADR 0004; re-meeting a still-trusted Peer uses mDNS/DNS-SD rediscovery and/or hints plus key proof. mDNS ads carry name and key fingerprint; full public key is fetched before challenge. Browse on start, network change, and slow periodic refresh. Same-LAN (or paste/USB) only — no relay in this pass.

**Superseded in part by [ADR-0011](0011-mtls-peer-meet-and-cache-file-share.md):** live Peer meet is mTLS on the Peer listener (cert pin / pairing TOFU), not cleartext HTTP + client-only `/api/prove`. Identity vs Locator, pairing for trust, and discovery scope here still stand.

## Considered Options

- Durable authoritative Peer URLs — rejected; IPs rot and are not Identity.
- No durable Locators at all — rejected; last-known hints speed reconnect when multicast is flaky, but success still requires key proof.
- Trust from static pairing payload alone — rejected; forgeable without proving key possession.
