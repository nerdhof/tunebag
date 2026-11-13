"""SoundCloud / hearthis fetch_bytes via injectable audio fetcher (no network)."""

from __future__ import annotations

from mixy.source import HearthisSource, SoundCloudSource


def test_soundcloud_fetch_bytes_uses_injected_fetcher() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"sc-audio"

    source = SoundCloudSource(audio_fetcher=fetcher)
    url = "https://soundcloud.com/dj-x/long-set"

    assert source.fetch_bytes(url) == b"sc-audio"
    assert calls == [url]


def test_hearthis_fetch_bytes_uses_injected_fetcher() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b"ht-audio"

    source = HearthisSource(audio_fetcher=fetcher)
    url = "https://hearthis.at/dj-y/marathon/"

    assert source.fetch_bytes(url) == b"ht-audio"
    assert calls == [url]
