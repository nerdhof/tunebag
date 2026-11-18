"""Artist URL normalize helpers and CompositeSource host routing."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from tunebag.domain import Platform

_YOUTUBE_HOSTS = frozenset({"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"})
_YOUTUBE_CHANNEL_TABS = frozenset(
    {"", "releases", "videos", "playlists", "featured", "about", "streams", "shorts"}
)


def bandcamp_normalize_artist_url(url: str) -> str | None:
    """Canonical `/music` URL for artist root or `/music`; else None."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if not host.endswith(".bandcamp.com") or host == "bandcamp.com":
        return None
    path = (parsed.path or "").rstrip("/").lower()
    if path not in ("", "/music"):
        return None
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}/music"


def youtube_normalize_artist_url(url: str) -> str | None:
    """Canonical www.youtube.com …/releases URL for channel forms; else None."""
    try:
        return youtube_artist_releases_url(url)
    except ValueError:
        return None


def youtube_artist_releases_url(artist_url: str) -> str:
    """Normalize channel forms to the releases tab; reject deep links."""
    parsed = urlparse(artist_url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in _YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        raise ValueError(f"not a YouTube URL: {artist_url}")

    path = parsed.path or "/"
    path_lower = path.lower()
    query = parse_qs(parsed.query)

    if host == "youtu.be" or path_lower.startswith("/watch"):
        raise ValueError(
            "YouTube watch URLs are not supported; "
            "add the artist channel (e.g. https://www.youtube.com/@HANDLE) "
            f"instead of {artist_url}"
        )
    if path_lower.startswith("/playlist") or (
        "list" in query and not youtube_is_channel_path(path_lower)
    ):
        raise ValueError(
            "YouTube playlist URLs are not supported; "
            "add the artist channel (e.g. https://www.youtube.com/@HANDLE) "
            f"instead of {artist_url}"
        )
    if path_lower.startswith("/browse"):
        raise ValueError(
            "YouTube Music album/browse URLs are not supported; "
            "add the artist channel (e.g. https://www.youtube.com/@HANDLE) "
            f"instead of {artist_url}"
        )

    channel_path = youtube_channel_path(path)
    if channel_path is None:
        raise ValueError(
            "YouTube artist URL must be a channel "
            "(@handle, /channel/UC…, /c/…, or /user/…); "
            f"got {artist_url}"
        )
    return f"https://www.youtube.com{channel_path}/releases"


def youtube_is_channel_path(path_lower: str) -> bool:
    return path_lower.startswith(("/@", "/channel/", "/c/", "/user/"))


def youtube_channel_path(path: str) -> str | None:
    """Return /@handle or /channel/UC… (no tab); None if not a channel form."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    head = parts[0]
    if head.startswith("@"):
        tab = parts[1].lower() if len(parts) > 1 else ""
        if tab not in _YOUTUBE_CHANNEL_TABS:
            return None
        return f"/{head}"
    if head == "channel" and len(parts) >= 2:
        tab = parts[2].lower() if len(parts) > 2 else ""
        if tab not in _YOUTUBE_CHANNEL_TABS:
            return None
        return f"/channel/{parts[1]}"
    if head in ("c", "user") and len(parts) >= 2:
        tab = parts[2].lower() if len(parts) > 2 else ""
        if tab not in _YOUTUBE_CHANNEL_TABS:
            return None
        return f"/{head}/{parts[1]}"
    return None


def youtube_channel_id_from_url(url: str) -> str | None:
    parts = [p for p in (urlparse(url.strip()).path or "").split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "channel" and parts[1].startswith("UC"):
        return parts[1]
    return None


def platform_for_url(url: str) -> Platform | None:
    """Map a media/artist URL host to an ingest Platform, or None if unsupported."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if "soundcloud.com" in host:
        return Platform.SOUNDCLOUD
    if "hearthis.at" in host:
        return Platform.HEARTHIS
    if "bandcamp.com" in host:
        return Platform.BANDCAMP
    if "youtube.com" in host or host == "youtu.be":
        return Platform.YOUTUBE
    return None
