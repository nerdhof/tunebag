# 02: Album Cache fill + intent folders

**What to build:** Assigned Album Releases fill by downloading each track into one cache directory for that Release. An Album counts as present only when every track is local. Intent folders expose each Album as a subfolder of ordered track files. Peer copy is all-or-nothing for the Album.

**Blocked by:** 01: Album Releases in Catalog (FakeSource)

**Status:** ready-for-agent

- [ ] Cache fill fetches per-track bytes for an Album (via FakeSource) into one directory keyed by the Release.
- [ ] An Album is not present in Cache until all tracks are local; incomplete directories do not satisfy “has file.”
- [ ] Failed/partial fills leave the Album absent (and do not strand a “present” half-disc).
- [ ] Intent folders place Mixes as single files and Albums as subfolders of ordered track files.
- [ ] Peer file copy for an Album transfers the whole track set or leaves the Album absent.
- [ ] Metered / assignment fill treats an Album Release like any other assigned Release (no special Bandcamp policy).
