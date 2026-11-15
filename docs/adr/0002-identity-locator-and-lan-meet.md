# Identity vs Locator, key proof, and LAN meet

Network addresses change across home/work/hackspace, so Identity (`device_id` + keypair) must not be a URL. Locators are ephemeral reachability hints (optionally last-known on disk); they never grant trust. Before Event log sync, the process at a Locator must pass a private-key challenge–response; the proof lasts for the live session only. QR or short code establishes trust (first pair or re-pair after unpair); re-meeting a trusted Peer uses mDNS/DNS-SD rediscovery and/or hints plus key proof. mDNS ads carry name and short code/fingerprint; full public key is fetched before challenge. Browse on start, network change, and slow periodic refresh. Same-LAN (or paste/USB) only — no relay in this pass.

## Considered Options

- Durable authoritative Peer URLs — rejected; IPs rot and are not Identity.
- No durable Locators at all — rejected; last-known hints speed reconnect when multicast is flaky, but success still requires key proof.
- Trust from static pairing payload alone — rejected; forgeable without proving key possession.
