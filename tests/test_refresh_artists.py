"""Issue 09: refresh artists — exercised only through DeviceAgent + FakeSource."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.reject import UNDO_SECONDS
from tunebag.source import ArtistListing, FakeSource, Upload


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _alpha_listing(*uploads: Upload) -> ArtistListing:
    return ArtistListing(
        platform=Platform.SOUNDCLOUD,
        platform_id="alpha",
        name="DJ Alpha",
        url="https://soundcloud.com/dj-alpha",
        uploads=list(uploads),
    )


def _beta_listing(*uploads: Upload) -> ArtistListing:
    return ArtistListing(
        platform=Platform.HEARTHIS,
        platform_id="beta",
        name="DJ Beta",
        url="https://hearthis.at/dj-beta/",
        uploads=list(uploads),
    )


def _long(platform: Platform, platform_id: str, title: str, url: str) -> Upload:
    return Upload(
        platform=platform,
        platform_id=platform_id,
        title=title,
        url=url,
        duration_seconds=3600,
    )


def _short(platform: Platform, platform_id: str, title: str, url: str) -> Upload:
    return Upload(
        platform=platform,
        platform_id=platform_id,
        title=title,
        url=url,
        duration_seconds=600,
    )


def _source_with_two_artists() -> FakeSource:
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _short(
                Platform.SOUNDCLOUD,
                "a-short",
                "Alpha Short",
                "https://soundcloud.com/dj-alpha/short",
            ),
        ),
    )
    source.add_listing(
        "https://hearthis.at/dj-beta/",
        _beta_listing(
            _long(
                Platform.HEARTHIS,
                "b1",
                "Beta Marathon",
                "https://hearthis.at/dj-beta/marathon/",
            ),
        ),
    )
    return source


def test_refresh_one_artist_adds_only_new_long_enough_uploads() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    alpha = next(a for a in laptop.artists() if a.name == "DJ Alpha")

    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _short(
                Platform.SOUNDCLOUD,
                "a-short",
                "Alpha Short",
                "https://soundcloud.com/dj-alpha/short",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
            _short(
                Platform.SOUNDCLOUD,
                "a-new-short",
                "Alpha New Short",
                "https://soundcloud.com/dj-alpha/new-short",
            ),
        ),
    )

    added = laptop.refresh_artists([alpha.id])

    assert [m.title for m in added] == ["Alpha New Set"]
    assert {m.title for m in laptop.mixes()} == {
        "Alpha Long Set",
        "Alpha New Set",
        "Beta Marathon",
    }
    assert source.fetch_calls == []


def test_refresh_all_catalog_artists_in_one_call() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
        ),
    )
    source.add_listing(
        "https://hearthis.at/dj-beta/",
        _beta_listing(
            _long(
                Platform.HEARTHIS,
                "b1",
                "Beta Marathon",
                "https://hearthis.at/dj-beta/marathon/",
            ),
            _long(
                Platform.HEARTHIS,
                "b2",
                "Beta New",
                "https://hearthis.at/dj-beta/new/",
            ),
        ),
    )

    added = laptop.refresh_artists()

    assert {m.title for m in added} == {"Alpha New Set", "Beta New"}
    assert {m.title for m in laptop.mixes()} == {
        "Alpha Long Set",
        "Alpha New Set",
        "Beta Marathon",
        "Beta New",
    }


def test_refresh_skips_existing_platform_ids() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    before = {m.id for m in laptop.mixes()}

    added = laptop.refresh_artists()

    assert added == []
    assert {m.id for m in laptop.mixes()} == before


def test_committed_reject_not_resurrected() -> None:
    clock = FakeClock()
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source, clock=clock)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    mix = laptop.mixes()[0]
    platform_id = mix.platform_id

    laptop.reject_mix(mix.id)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()
    assert laptop.catalog.mixes[mix.id].rejected is True

    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                platform_id,
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
        ),
    )

    added = laptop.refresh_artists()

    assert [m.title for m in added] == ["Alpha New Set"]
    same = [m for m in laptop.mixes() if m.platform_id == platform_id]
    assert len(same) == 1
    assert same[0].id == mix.id
    assert same[0].rejected is True


def test_custom_min_duration_on_refresh() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _short(
                Platform.SOUNDCLOUD,
                "a-short",
                "Alpha Short",
                "https://soundcloud.com/dj-alpha/short",
            ),
        ),
    )

    added = laptop.refresh_artists(min_duration_seconds=0)

    assert {m.title for m in added} == {"Alpha Short"}


def test_refresh_creates_no_audio() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
        ),
    )

    laptop.refresh_artists()

    assert laptop.files() == []
    assert source.fetch_calls == []


def test_paired_peer_sees_new_rows_after_sync() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    laptop.sync()
    phone.sync()

    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
        ),
    )
    laptop.refresh_artists()
    laptop.sync()
    phone.sync()

    assert {m.title for m in phone.mixes()} == {"Alpha Long Set", "Alpha New Set"}
    assert phone.files() == []
    assert source.fetch_calls == []


def test_refresh_unknown_artist_raises() -> None:
    laptop = DeviceAgent("laptop", source=FakeSource())
    with pytest.raises(KeyError, match="unknown artist"):
        laptop.refresh_artists([uuid4()])


def test_refresh_artists_rebuilds_unfilled_sequence_and_fills_cache() -> None:
    source = _source_with_two_artists()
    source.bytes_by_url["https://soundcloud.com/dj-alpha/long"] = b"audio:alpha-long"
    source.bytes_by_url["https://soundcloud.com/dj-alpha/new"] = b"audio:alpha-new"
    laptop = DeviceAgent("laptop", source=source)
    intent = laptop.create_intent(
        "Explore",
        tags=[],
        seed=1,
        device_hours=[(laptop.device_id, 8 * 3600)],
    )
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    laptop.wait_for_fill(timeout=5.0)
    first = laptop.mixes()[0]
    assert [e.mix_id for e in laptop.sequence(intent.id).entries] == [first.id]
    assert {m.id for m in laptop.files()} == {first.id}

    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        _alpha_listing(
            _long(
                Platform.SOUNDCLOUD,
                "a1",
                "Alpha Long Set",
                "https://soundcloud.com/dj-alpha/long",
            ),
            _long(
                Platform.SOUNDCLOUD,
                "a2",
                "Alpha New Set",
                "https://soundcloud.com/dj-alpha/new",
            ),
        ),
    )
    laptop.refresh_artists()
    laptop.wait_for_fill(timeout=5.0)

    titles = {laptop.catalog.mixes[e.mix_id].title for e in laptop.sequence(intent.id).entries}
    assert titles == {"Alpha Long Set", "Alpha New Set"}
    assignment = laptop.assignment(intent.id, laptop.device_id)
    assert assignment is not None
    assert set(assignment.mix_ids) == {m.id for m in laptop.mixes()}
    assert {m.id for m in laptop.files()} == {m.id for m in laptop.mixes()}
    assert "https://soundcloud.com/dj-alpha/new" in source.fetch_calls
