"""Display-time title cleanup for companion UI (Catalog / Event data stay raw)."""

from __future__ import annotations

import re

# Entire bracket / paren inner text that is upload packaging, not song identity.
# Optional trailing "track" / resolution covers forms like
# "(OFFICIAL VISUALIZER TRACK)" and "(Official Music Video HD)".
_PACKAGING_KIND = r"""
    (?:
        lyrics?\s*video
      | lyric\s*videos?
      | music\s*video
      | video
      | audio
      | visuali[sz]er
      | version
    )
    (?:\s+track)?
"""

_PACKAGING_INNER = re.compile(
    rf"""(?ix)
    ^\s*
    (?:
        # EN official* packaging
        official
        (?:\s+(?:hd|4k|8k|hq))?
        (?:\s+(?:{_PACKAGING_KIND}))?
        (?:\s+(?:hd|4k|8k|hq))?
      | (?:official\s+)?(?:{_PACKAGING_KIND})
      | audio(?:\s+only)?
      | performance\s+video
      | animated\s+music\s+video
      | promo\s+video
      | 360\s+reality\s+audio\s*/\s*official\s+audio
      # DE (incl. common "Muiskvideo" typo)
      | offizielles?
        (?:\s+
            (?:
                (?:musik|muisk)video
              | video
                (?:\s*[-–—]\s*refurbished\s*\d{{4}})?
              | version
            )
        )?
        (?:\s+(?:hd|4k|8k|hq))?
      # resolution-only / HD version tags
      | (?:hd|4k|8k|hq)\s+version
      | (?:4k|8k|1080p|720p|480p|hd|hq)
    )
    \s*$
    """
)

_BRACKET_GROUP = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")

# Trailing unbracketed packaging after a separator or space.
_TRAILING_PACKAGING = re.compile(
    rf"""(?ix)
    (?:
        \s*[-–—|:]\s*
      | \s+
    )
    (?:
        (?:offizielles?|official)
        (?:\s+(?:hd|4k|8k|hq))?
        (?:\s+(?:{_PACKAGING_KIND}|(?:musik|muisk)video))?
        (?:\s+(?:hd|4k|8k|hq))?
      | (?:official\s+)?(?:{_PACKAGING_KIND})
      | lyric\s*videos?
      | lyrics?\s*video
    )
    \s*$
    """
)

_MULTI_SPACE = re.compile(r"\s{2,}")


def display_title(title: str, *, artist: str | None = None) -> str:
    """Return a UI-friendly title; never mutate Catalog / Event source strings.

    Strips EN/DE upload packaging tags and an optional matching artist prefix.
    Leaves Live / feat / remaster / soundtrack suffixes alone.
    """
    original = title
    text = str(title or "").strip()
    if not text:
        return ""

    text = _strip_packaging_brackets(text)
    text = _TRAILING_PACKAGING.sub("", text).strip()
    text = _MULTI_SPACE.sub(" ", text).strip()

    name = str(artist or "").strip()
    if name:
        prefix = re.compile(
            rf"^{re.escape(name)}\s*[-–—:]\s*",
            re.IGNORECASE,
        )
        stripped = prefix.sub("", text, count=1).strip()
        if stripped:
            text = stripped

    text = _MULTI_SPACE.sub(" ", text).strip(" -–—|:").strip()
    if not text:
        return str(original).strip() or original
    return text


def _strip_packaging_brackets(text: str) -> str:
    """Remove bracket groups whose entire inner text is packaging vocabulary."""

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if _PACKAGING_INNER.match(inner):
            return ""
        return match.group(0)

    # Repeat until stable so adjacent tags like "(Official Video) [HD]" both go.
    prev = None
    while prev != text:
        prev = text
        text = _BRACKET_GROUP.sub(_repl, text)
        text = _MULTI_SPACE.sub(" ", text).strip()
    return text
