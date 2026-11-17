"""CompositeSource host dispatch — no network."""

from __future__ import annotations

import pytest

from tunebag.domain import Platform
from tunebag.source import ArtistListing, CompositeSource, Upload


class _Stub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.listed: list[str] = []
        self.fetched: list[str] = []

    def list_uploads(self, artist_url: str) -> ArtistListing:
        self.listed.append(artist_url)
        return ArtistListing(
            platform=Platform.OTHER,
            platform_id=self.name,
            name=self.name,
            url=artist_url,
            uploads=[
                Upload(
                    platform=Platform.OTHER,
                    platform_id="1",
                    title="t",
                    url=artist_url + "/t",
                    duration_seconds=3600,
                )
            ],
        )

    def fetch_bytes(self, source_url: str, *, on_progress=None) -> bytes:
        self.fetched.append(source_url)
        if on_progress is not None:
            on_progress(len(b"x"), len(b"x"))
        return b"x"


def test_composite_routes_soundcloud_and_hearthis() -> None:
    sc = _Stub("sc")
    ht = _Stub("ht")
    source = CompositeSource(soundcloud=sc, hearthis=ht)

    source.list_uploads("https://soundcloud.com/dj-x")
    source.list_uploads("https://www.hearthis.at/dj-y/")
    source.fetch_bytes("https://soundcloud.com/dj-x/track")
    source.fetch_bytes("https://hearthis.at/dj-y/track/")

    assert sc.listed == ["https://soundcloud.com/dj-x"]
    assert ht.listed == ["https://www.hearthis.at/dj-y/"]
    assert sc.fetched == ["https://soundcloud.com/dj-x/track"]
    assert ht.fetched == ["https://hearthis.at/dj-y/track/"]


def test_composite_routes_bandcamp_artist_hosts() -> None:
    sc = _Stub("sc")
    ht = _Stub("ht")
    bc = _Stub("bc")
    source = CompositeSource(soundcloud=sc, hearthis=ht, bandcamp=bc)

    source.list_uploads("https://chrishuelsbeck.bandcamp.com/music")
    source.list_uploads("https://chrishuelsbeck.bandcamp.com")
    source.fetch_bytes("https://chrishuelsbeck.bandcamp.com/track/scores")

    assert bc.listed == [
        "https://chrishuelsbeck.bandcamp.com/music",
        "https://chrishuelsbeck.bandcamp.com",
    ]
    assert bc.fetched == ["https://chrishuelsbeck.bandcamp.com/track/scores"]
    assert sc.listed == []
    assert ht.listed == []


def test_composite_rejects_unknown_host() -> None:
    source = CompositeSource(
        soundcloud=_Stub("sc"),
        hearthis=_Stub("ht"),
        bandcamp=_Stub("bc"),
    )
    with pytest.raises(ValueError, match="unsupported artist URL host"):
        source.list_uploads("https://mixcloud.com/artist")


def test_soundcloud_upload_reads_optional_size_bytes() -> None:
    from tunebag.source import _soundcloud_upload

    upload = _soundcloud_upload(
        {
            "id": 99,
            "title": "Set",
            "permalink_url": "https://soundcloud.com/dj/set",
            "duration": 3_600_000,
            "original_content_size": 50_000_000,
        }
    )
    assert upload is not None
    assert upload.size_bytes == 50_000_000

    bare = _soundcloud_upload(
        {
            "id": 100,
            "title": "Bare",
            "permalink_url": "https://soundcloud.com/dj/bare",
            "duration": 3_600_000,
        }
    )
    assert bare is not None
    assert bare.size_bytes is None
