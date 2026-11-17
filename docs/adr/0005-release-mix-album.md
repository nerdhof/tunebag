# Release umbrella: Mix and Album

Catalog listening items are **Releases**. A Release is either a **Mix** (single audio file) or an **Album** (ordered tracks; duration/size are sums; Played and Playhead use the whole-album timeline). We rejected keeping Mix as the only primitive and stuffing albums into one concatenated blob, and rejected a separate non-Release Album type. Wire/API names may still say `mix` / `mix_id` until a dedicated rename pass; `CONTEXT.md` is authoritative for language.
