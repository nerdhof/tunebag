"""CompositeSource host dispatch — no network."""

from __future__ import annotations

import pytest

from mixy.domain import Platform
from mixy.source import ArtistListing, CompositeSource, Upload


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


def test_composite_rejects_unknown_host() -> None:
    source = CompositeSource(soundcloud=_Stub("sc"), hearthis=_Stub("ht"))
    with pytest.raises(ValueError, match="unsupported artist URL host"):
        source.list_uploads("https://bandcamp.com/artist")
