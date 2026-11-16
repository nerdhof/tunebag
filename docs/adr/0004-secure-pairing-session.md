# Secure pairing via ephemeral session, PIN, and dual SAS confirm

Static QR / short-code trust was forgeable on a hostile LAN: short codes did not bind key material, `POST /api/pair/accept` accepted unauthenticated offers, and a glimpse of a durable QR was enough to pair. Trust is now established only through an ephemeral pairing session: host shows a short-lived one-time PIN (optional QR encodes the same offer), guest joins with a signed transcript, both devices show a matching SAS and must Confirm before either writes `DEVICE_PAIRED`. Fingerprints derived from raw public-key bytes label devices in discovery; they are not pairing secrets. Re-meeting a still-trusted Peer is unchanged (Locator + key proof per ADR 0002).

## Considered Options

- Longer durable short codes as secrets — rejected; durable codes remain glimpse- and replay-friendly and do not give mutual auth.
- PAKE (e.g. SPAKE2) — deferred; dual human confirm + SAS gives mutual auth with existing Ed25519 and no new dependency.
- QR-only with confirm — rejected; not every device can scan a camera.
