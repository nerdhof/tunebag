"""Issue 02: add artists — exercised only through DeviceAgent + FakeSource."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from tunebag.agent import EXPLORE_INTENT_ID, DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import ArtistListing, FakeSource, Upload


def _source_with_two_artists() -> FakeSource:
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="alpha",
            name="DJ Alpha",
            url="https://soundcloud.com/dj-alpha",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a1",
                    title="Alpha Long Set",
                    url="https://soundcloud.com/dj-alpha/long",
                    duration_seconds=3600,
                    size_bytes=12_345_678,
                ),
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a-short",
                    title="Alpha Short",
                    url="https://soundcloud.com/dj-alpha/short",
                    duration_seconds=600,
                ),
            ],
        ),
    )
    source.add_listing(
        "https://hearthis.at/dj-beta/",
        ArtistListing(
            platform=Platform.HEARTHIS,
            platform_id="beta",
            name="DJ Beta",
            url="https://hearthis.at/dj-beta/",
            uploads=[
                Upload(
                    platform=Platform.HEARTHIS,
                    platform_id="b1",
                    title="Beta Marathon",
                    url="https://hearthis.at/dj-beta/marathon/",
                    duration_seconds=7200,
                ),
            ],
        ),
    )
    return source


def test_one_artist_url_adds_catalog_rows_without_audio() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    mixes = laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    assert [m.title for m in mixes] == ["Alpha Long Set"]
    assert [m.title for m in laptop.mixes()] == ["Alpha Long Set"]
    long = laptop.mixes()[0]
    assert long.duration_seconds == 3600
    assert long.size_bytes == 12_345_678
    assert long.url == "https://soundcloud.com/dj-alpha/long"
    assert [a.name for a in laptop.artists()] == ["DJ Alpha"]
    assert laptop.files() == []
    assert source.fetch_calls == []


def test_several_artist_urls_in_one_step() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )

    titles = {m.title for m in laptop.mixes()}
    assert titles == {"Alpha Long Set", "Beta Marathon"}
    assert {a.name for a in laptop.artists()} == {"DJ Alpha", "DJ Beta"}


def test_adding_same_artist_url_again_does_not_duplicate() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    first = laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    artist_id = laptop.artists()[0].id
    second = laptop.add_artists(["https://soundcloud.com/dj-alpha/"])

    assert [a.id for a in laptop.artists()] == [artist_id]
    assert [m.title for m in laptop.mixes()] == ["Alpha Long Set"]
    assert [m.id for m in laptop.mixes()] == [first[0].id]
    assert second == []


def test_youtube_host_and_tab_forms_dedupe_to_one_artist() -> None:
    """Music host / bare handle /releases normalize like Bandcamp root vs /music."""
    album = Upload(
        platform=Platform.YOUTUBE,
        platform_id="OLAK5uy_examplealbumid00000000000000",
        title="Lateralus",
        url="https://www.youtube.com/playlist?list=OLAK5uy_examplealbumid00000000000000",
        duration_seconds=3600,
        tracks=(),
    )
    music_url = "https://music.youtube.com/@TOOLmusic"
    releases_url = "https://www.youtube.com/@TOOLmusic/releases"
    source = FakeSource()
    source.add_listing(
        music_url,
        ArtistListing(
            platform=Platform.YOUTUBE,
            platform_id="UCtoolchannel000000000000",
            name="TOOL",
            url=music_url,
            uploads=[album],
        ),
    )
    source.add_listing(
        releases_url,
        ArtistListing(
            platform=Platform.YOUTUBE,
            platform_id="UCtoolchannel000000000000",
            name="TOOL",
            url=releases_url,
            uploads=[album],
        ),
    )
    laptop = DeviceAgent("laptop", source=source)

    first = laptop.add_artists([music_url])
    artist_id = laptop.artists()[0].id
    second = laptop.add_artists([releases_url])

    assert [a.id for a in laptop.artists()] == [artist_id]
    assert len(laptop.mixes()) == 1
    assert second == []
    assert [m.id for m in laptop.mixes()] == [first[0].id]


def test_readding_artist_url_adds_only_new_uploads() -> None:
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="alpha",
            name="DJ Alpha",
            url="https://soundcloud.com/dj-alpha",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a1",
                    title="Alpha Long Set",
                    url="https://soundcloud.com/dj-alpha/long",
                    duration_seconds=3600,
                ),
            ],
        ),
    )
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="alpha",
            name="DJ Alpha",
            url="https://soundcloud.com/dj-alpha",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a1",
                    title="Alpha Long Set",
                    url="https://soundcloud.com/dj-alpha/long",
                    duration_seconds=3600,
                ),
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a2",
                    title="Alpha Night",
                    url="https://soundcloud.com/dj-alpha/night",
                    duration_seconds=4000,
                ),
            ],
        ),
    )
    added = laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    assert len(laptop.artists()) == 1
    assert {m.title for m in laptop.mixes()} == {"Alpha Long Set", "Alpha Night"}
    assert [m.title for m in added] == ["Alpha Night"]


def test_default_min_duration_drops_short_uploads() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    assert "Alpha Short" not in {m.title for m in laptop.mixes()}


def test_custom_min_duration_seconds_changes_cut() -> None:
    include_short = DeviceAgent("open", source=_source_with_two_artists())
    include_short.add_artists(
        ["https://soundcloud.com/dj-alpha"],
        min_duration_seconds=0,
    )
    assert {m.title for m in include_short.mixes()} == {"Alpha Long Set", "Alpha Short"}

    only_longer = DeviceAgent("strict", source=_source_with_two_artists())
    only_longer.add_artists(
        ["https://soundcloud.com/dj-alpha"],
        min_duration_seconds=4000,
    )
    assert only_longer.mixes() == []


def test_paired_peer_sees_rows_after_sync_without_files() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    laptop.sync()
    phone.sync()

    assert {m.title for m in phone.mixes()} == {"Alpha Long Set", "Beta Marathon"}
    assert {m.url for m in phone.mixes()} == {
        "https://soundcloud.com/dj-alpha/long",
        "https://hearthis.at/dj-beta/marathon/",
    }
    assert phone.files() == []
    assert source.fetch_calls == []


def test_delete_artist_removes_artist_and_mixes(tmp_path: Path) -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source, data_dir=tmp_path / "laptop")
    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    alpha = next(a for a in laptop.artists() if a.name == "DJ Alpha")
    alpha_mix = next(m for m in laptop.mixes() if m.artist_id == alpha.id)
    laptop._store_local_file(alpha_mix.id, b"audio:alpha")
    assert laptop.files()

    laptop.delete_artist(alpha.id)

    assert [a.name for a in laptop.artists()] == ["DJ Beta"]
    assert [m.title for m in laptop.mixes()] == ["Beta Marathon"]
    assert laptop.files() == []
    assert laptop.file_bytes(alpha_mix.id) is None


def test_delete_artist_syncs_to_peer() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    laptop.sync()
    phone.sync()
    alpha = next(a for a in laptop.artists() if a.name == "DJ Alpha")

    laptop.delete_artist(alpha.id)
    laptop.sync()
    phone.sync()

    assert {a.name for a in phone.artists()} == {"DJ Beta"}
    assert {m.title for m in phone.mixes()} == {"Beta Marathon"}


def test_delete_artist_rebuilds_sequences() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    alpha = laptop.artists()[0]
    mix = laptop.mixes()[0]
    laptop.tag_mix(mix.id, ["deep"])
    laptop.rate_mix(mix.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Deep",
        tags=["deep"],
        seed=1,
        device_hours=[(laptop.device_id, 3600), (phone.device_id, 3600)],
    )
    laptop.sync()
    phone.sync()
    assert [e.mix_id for e in laptop.sequence(intent.id).entries] == [mix.id]

    laptop.delete_artist(alpha.id)
    laptop.sync()
    phone.sync()

    assert laptop.sequence(intent.id).entries == []
    assert phone.sequence(intent.id).entries == []
    assert mix.id not in (laptop.assignment(intent.id, laptop.device_id).mix_ids or [])


def test_delete_unknown_artist_raises() -> None:
    laptop = DeviceAgent("laptop", source=FakeSource())
    with pytest.raises(KeyError, match="unknown artist"):
        laptop.delete_artist(uuid4())


def test_add_artists_rebuilds_unfilled_sequence_and_fills_cache() -> None:
    source = _source_with_two_artists()
    source.bytes_by_url["https://soundcloud.com/dj-alpha/long"] = b"audio:alpha-long"
    laptop = DeviceAgent("laptop", source=source)
    intent = laptop.create_intent(
        "Explore",
        tags=[],
        seed=1,
        device_hours=[(laptop.device_id, 8 * 3600)],
    )
    assert laptop.sequence(intent.id).entries == []

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    laptop.wait_for_fill(timeout=5.0)

    mix = laptop.mixes()[0]
    entries = laptop.sequence(intent.id).entries
    assert [e.mix_id for e in entries] == [mix.id]
    assignment = laptop.assignment(intent.id, laptop.device_id)
    assert assignment is not None
    assert assignment.mix_ids == [mix.id]
    assert {m.id for m in laptop.files()} == {mix.id}
    assert mix.url in source.fetch_calls


def test_add_artists_leaves_filled_sequence_alone() -> None:
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="alpha",
            name="DJ Alpha",
            url="https://soundcloud.com/dj-alpha",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a1",
                    title="Alpha Hour",
                    url="https://soundcloud.com/dj-alpha/hour",
                    duration_seconds=3600,
                ),
            ],
        ),
    )
    source.add_listing(
        "https://soundcloud.com/dj-gamma",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="gamma",
            name="DJ Gamma",
            url="https://soundcloud.com/dj-gamma",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="g1",
                    title="Gamma Hour",
                    url="https://soundcloud.com/dj-gamma/hour",
                    duration_seconds=3600,
                ),
            ],
        ),
    )
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    intent = laptop.create_intent(
        "Explore",
        tags=[],
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    # Intent upsert may attempt a fill (no bytes configured); settle before asserts.
    laptop.wait_for_fill()
    source.fetch_calls.clear()
    before = [e.mix_id for e in laptop.sequence(intent.id).entries]
    assert len(before) == 1

    laptop.add_artists(["https://soundcloud.com/dj-gamma"])

    after = [e.mix_id for e in laptop.sequence(intent.id).entries]
    assert after == before
    assert {m.title for m in laptop.mixes()} == {"Alpha Hour", "Gamma Hour"}
    assert laptop.files() == []
    assert source.fetch_calls == []


def test_paired_new_device_rebuilds_explore_and_fills_cache_from_peer_artists(
    tmp_path: Path,
) -> None:
    """Artists from an existing peer must refresh unfilled intents + cache on the new device."""
    source = _source_with_two_artists()
    source.bytes_by_url["https://soundcloud.com/dj-alpha/long"] = b"audio:alpha-long"
    laptop = DeviceAgent("laptop", priority=1, source=source, data_dir=tmp_path / "laptop")
    assert laptop.seed_default_intents_if_empty() is True
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    laptop.wait_for_fill(timeout=5.0)
    mix = laptop.mixes()[0]
    assert {m.id for m in laptop.files()} == {mix.id}

    phone = DeviceAgent("phone", priority=10, source=FakeSource(), data_dir=tmp_path / "phone")
    assert phone.seed_default_intents_if_empty() is True
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    phone.sync()
    phone.wait_for_fill(timeout=5.0)

    assert {m.title for m in phone.mixes()} == {"Alpha Long Set"}
    assignment = phone.assignment(EXPLORE_INTENT_ID, phone.device_id)
    assert assignment is not None
    assert mix.id in assignment.mix_ids
    assert {m.id for m in phone.files()} == {mix.id}


def test_paired_phone_keeps_empty_seed_assignment_until_rebuild_when_sequence_already_filled(
    tmp_path: Path,
) -> None:
    """Explore seed writes assignment mix_ids=[] ; a later filled peer sequence must rebuild it.

    If the laptop's filled SEQUENCE wins LWW over the phone's empty seed sequence,
    under-budget rebuild alone is a no-op (same mix ids). The phone's empty
    assignment must still be treated as needing rebuild so cache can fill.
    """
    from datetime import datetime, timedelta

    class FakeClock:
        def __init__(self) -> None:
            self._now = datetime(2024, 6, 1, 12, 0, 0)

        def __call__(self) -> datetime:
            return self._now

        def advance(self, seconds: float) -> None:
            self._now += timedelta(seconds=seconds)

    source = _source_with_two_artists()
    source.bytes_by_url["https://soundcloud.com/dj-alpha/long"] = b"audio:alpha-long"
    clock = FakeClock()

    phone = DeviceAgent(
        "phone",
        priority=10,
        source=FakeSource(),
        data_dir=tmp_path / "phone",
        clock=clock,
    )
    assert phone.seed_default_intents_if_empty() is True
    phone_asg = phone.assignment(EXPLORE_INTENT_ID, phone.device_id)
    assert phone_asg is not None
    assert phone_asg.mix_ids == []

    clock.advance(60)
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    assert laptop.seed_default_intents_if_empty() is True
    clock.advance(60)
    laptop.add_artists(["https://soundcloud.com/dj-alpha"])
    laptop.wait_for_fill(timeout=5.0)
    mix = laptop.mixes()[0]
    # Laptop sequence/assignment author times are after phone's empty seed.
    assert laptop.sequence(EXPLORE_INTENT_ID).entries

    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    phone.sync()
    phone.wait_for_fill(timeout=5.0)

    assert phone.sequence(EXPLORE_INTENT_ID) is not None
    assert len(phone.sequence(EXPLORE_INTENT_ID).entries) >= 1
    assignment = phone.assignment(EXPLORE_INTENT_ID, phone.device_id)
    assert assignment is not None
    assert mix.id in assignment.mix_ids
    assert {m.id for m in phone.files()} == {mix.id}
