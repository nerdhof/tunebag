Status: resolved
Type: research

# Revisit playback backend after hygiene + request-path fixes?

## Question

After fixing subprocess hygiene and moving peer/fill work off the skip/mark-played request path, should Tunebag switch the `AudioPlayer` backend (mpv IPC, in-process, GStreamer/ffmpeg bindings)?

## Answer

**Defer.** Keep `SubprocessPlayer` (ffplay/afplay) until an audible stop/start gap or missing true-pause is still painful after the hygiene/request-path work.

Order if revisited:

1. **mpv with IPC** — still subprocess, instant quit, true pause/seek without respawn; fits existing `AudioPlayer` protocol.
2. **libmpv / miniaudio-style in-process** — only if avoiding an external binary matters.
3. **Avoid GStreamer / ffmpeg Python bindings** unless pipelines/transcoding appear — heavy native deps for play/stop/seek of local files.

Success gate for reopening: measure skip/mark-played wall time with peers down (target ≪300ms local) and confirm any remaining lag is the audio child stop/start, not catalog fillup or peer HTTP.
