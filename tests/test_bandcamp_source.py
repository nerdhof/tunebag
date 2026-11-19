"""BandcampSource — injectable HTTP, no live network."""

from __future__ import annotations

import json
from html import escape

import httpx
import pytest

from tunebag.domain import Platform
from tunebag.source import BandcampSource


def _band_attr(band_id: int = 42, name: str = "Example") -> str:
    return escape(json.dumps({"id": band_id, "name": name}), quote=True)


def _tralbum_attr(
    *,
    album_id: int,
    title: str,
    tracks: list[dict],
    free_download_page: str | None = None,
    minimum_price: float = 0.0,
    art_id: int | None = None,
) -> str:
    payload = {
        "id": album_id,
        "url": f"https://example.bandcamp.com/album/{title.lower().replace(' ', '-')}",
        "current": {"title": title, "minimum_price": minimum_price, "id": album_id},
        "trackinfo": tracks,
        "freeDownloadPage": free_download_page,
    }
    if art_id is not None:
        payload["art_id"] = art_id
    return escape(json.dumps(payload), quote=True)


def _music_html(*, album_paths: list[str]) -> str:
    links = "\n".join(f'<a href="{path}">album</a>' for path in album_paths)
    return f"""
    <html><body>
      <div data-band="{_band_attr()}"></div>
      <ol id="music-grid">{links}</ol>
    </body></html>
    """


def _album_html(
    *,
    album_id: int,
    title: str,
    tracks: list[dict],
    free_download_page: str | None = "https://bandcamp.com/download?id=1",
    minimum_price: float = 0.0,
    art_id: int | None = None,
) -> str:
    return f"""
    <html><body>
      <div data-tralbum="{_tralbum_attr(
        album_id=album_id,
        title=title,
        tracks=tracks,
        free_download_page=free_download_page,
        minimum_price=minimum_price,
        art_id=art_id,
    )}"></div>
    </body></html>
    """


def _streamable_track(
    *,
    track_id: int,
    title: str,
    duration: float,
    slug: str,
) -> dict:
    return {
        "track_id": track_id,
        "title": title,
        "duration": duration,
        "title_link": f"/track/{slug}",
        "file": {"mp3-128": f"https://t4.bcbits.com/stream/{track_id}"},
    }


def _locked_track(*, track_id: int, title: str, duration: float, slug: str) -> dict:
    return {
        "track_id": track_id,
        "title": title,
        "duration": duration,
        "title_link": f"/track/{slug}",
        "file": None,
    }


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).rstrip("/")
        # Allow with or without trailing slash / query.
        for key, body in self.pages.items():
            if url == key.rstrip("/") or url.startswith(key.rstrip("/") + "?"):
                return httpx.Response(200, text=body)
        return httpx.Response(404, text=f"missing {url}")


def _source_with_pages(pages: dict[str, str]) -> BandcampSource:
    client = httpx.Client(transport=_FakeTransport(pages), follow_redirects=True)
    return BandcampSource(client=client)


def test_bandcamp_rejects_album_page_url() -> None:
    source = BandcampSource(client=httpx.Client(transport=_FakeTransport({})))
    with pytest.raises(ValueError, match=r"artist .*?/music"):
        source.list_uploads("https://example.bandcamp.com/album/turrican")


def test_bandcamp_root_and_music_normalize_to_same_artist() -> None:
    music = _music_html(album_paths=[])
    pages = {
        "https://example.bandcamp.com/music": music,
        "https://example.bandcamp.com": music,
    }
    source = _source_with_pages(pages)

    a = source.list_uploads("https://example.bandcamp.com")
    b = source.list_uploads("https://example.bandcamp.com/music")

    assert a.platform == Platform.BANDCAMP
    assert a.platform_id == "42"
    assert a.name == "Example"
    assert a.url == b.url == "https://example.bandcamp.com/music"
    assert a.uploads == b.uploads == []


def test_bandcamp_lists_free_full_albums_with_tracks() -> None:
    tracks = [
        _streamable_track(
            track_id=1, title="One", duration=600.0, slug="one"
        ),
        _streamable_track(
            track_id=2, title="Two", duration=700.0, slug="two"
        ),
    ]
    pages = {
        "https://example.bandcamp.com/music": _music_html(
            album_paths=["/album/full-disc"]
        ),
        "https://example.bandcamp.com/album/full-disc": _album_html(
            album_id=99,
            title="Full Disc",
            tracks=tracks,
            art_id=1234567890,
        ),
    }
    source = _source_with_pages(pages)

    listing = source.list_uploads("https://example.bandcamp.com/music")

    assert len(listing.uploads) == 1
    album = listing.uploads[0]
    assert album.platform == Platform.BANDCAMP
    assert album.platform_id == "99"
    assert album.title == "Full Disc"
    assert album.url == "https://example.bandcamp.com/album/full-disc"
    assert album.duration_seconds == 1300
    assert album.cover_url == "https://f4.bcbits.com/img/a1234567890_10.jpg"
    assert len(album.tracks) == 2
    assert album.tracks[0].platform_id == "1"
    assert album.tracks[0].title == "One"
    assert album.tracks[0].url == "https://example.bandcamp.com/track/one"
    assert album.tracks[0].duration_seconds == 600
    assert album.tracks[1].platform_id == "2"


def test_bandcamp_skips_locked_album_without_aborting_artist() -> None:
    free_tracks = [
        _streamable_track(
            track_id=1, title="A", duration=600.0, slug="a"
        ),
        _streamable_track(
            track_id=2, title="B", duration=600.0, slug="b"
        ),
    ]
    locked_tracks = [
        _locked_track(track_id=3, title="X", duration=600.0, slug="x"),
        _streamable_track(
            track_id=4, title="Y", duration=600.0, slug="y"
        ),
    ]
    paid_streamable = [
        _streamable_track(
            track_id=5, title="P1", duration=600.0, slug="p1"
        ),
        _streamable_track(
            track_id=6, title="P2", duration=600.0, slug="p2"
        ),
    ]
    pages = {
        "https://example.bandcamp.com/music": _music_html(
            album_paths=["/album/locked", "/album/paid", "/album/free"]
        ),
        "https://example.bandcamp.com/album/locked": _album_html(
            album_id=1,
            title="Locked",
            tracks=locked_tracks,
            free_download_page=None,
            minimum_price=9.0,
        ),
        "https://example.bandcamp.com/album/paid": _album_html(
            album_id=3,
            title="Paid Streams",
            tracks=paid_streamable,
            free_download_page=None,
            minimum_price=9.0,
        ),
        "https://example.bandcamp.com/album/free": _album_html(
            album_id=2,
            title="Free",
            tracks=free_tracks,
        ),
    }
    source = _source_with_pages(pages)

    listing = source.list_uploads("https://example.bandcamp.com/music")

    # Partial/locked skipped; paid-but-fully-streamable kept with free.
    assert [u.platform_id for u in listing.uploads] == ["3", "2"]
    assert [u.title for u in listing.uploads] == ["Paid Streams", "Free"]


def test_bandcamp_fetch_bytes_uses_injected_fetcher() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"bc-audio"

    source = BandcampSource(audio_fetcher=fetcher)
    url = "https://example.bandcamp.com/track/one"

    assert source.fetch_bytes(url) == b"bc-audio"
    assert calls == [url]
