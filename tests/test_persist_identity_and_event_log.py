"""Issue 02 (durable-sync): identity + Event log persist; Catalog via replay."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import EXPLORE_INTENT_ID, EXPLORE_SEED, DeviceAgent
from tunebag.domain import Platform
from tunebag.source import ArtistListing, FakeSource, Upload


def test_device_identity_survives_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    first = DeviceAgent("laptop", data_dir=data_dir)
    device_id = first.device_id
    public_key = first.public_key_pem

    second = DeviceAgent("laptop", data_dir=data_dir)

    assert second.device_id == device_id
    assert second.public_key_pem == public_key


def test_first_boot_seeds_explore_intent(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    first = DeviceAgent("laptop", data_dir=data_dir)
    assert first.intents() == []
    assert first.seed_default_intents_if_empty() is True

    intents = first.intents()
    assert len(intents) == 1
    explore = intents[0]
    assert explore.id == EXPLORE_INTENT_ID
    assert explore.seed == EXPLORE_SEED
    assert explore.name == "Explore"
    assert explore.tags == []
    assert explore.distribution.five == 0.1
    assert explore.distribution.four == 0.1
    assert explore.distribution.three == 0.1
    assert explore.distribution.two == 0.1
    assert explore.distribution.one == 0.1
    assert explore.distribution.unrated == 0.5
    assert explore.device_hours == []

    first.delete_intent(EXPLORE_INTENT_ID)
    assert first.intents() == []

    # Restart does not recreate Explore once the Event log is non-empty.
    second = DeviceAgent("laptop", data_dir=data_dir)
    assert second.seed_default_intents_if_empty() is False
    assert second.intents() == []
    assert EXPLORE_INTENT_ID not in second.catalog.intents


def test_paired_devices_share_one_explore_intent(tmp_path: Path) -> None:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    assert laptop.seed_default_intents_if_empty() is True
    assert phone.seed_default_intents_if_empty() is True
    assert laptop.intents()[0].id == EXPLORE_INTENT_ID
    assert phone.intents()[0].id == EXPLORE_INTENT_ID

    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.sync()
    phone.sync()

    assert len(laptop.intents()) == 1
    assert len(phone.intents()) == 1
    assert laptop.intents()[0].id == EXPLORE_INTENT_ID
    assert phone.intents()[0].id == EXPLORE_INTENT_ID
    assert laptop.intents()[0].seed == EXPLORE_SEED
    assert phone.intents()[0].seed == EXPLORE_SEED


def _source_with_artist() -> FakeSource:
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
    return source


def test_catalog_rebuilds_from_event_log_after_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    source = _source_with_artist()
    first = DeviceAgent("laptop", source=source, data_dir=data_dir)
    first.add_artists(["https://soundcloud.com/dj-alpha"])
    artist_ids = {a.id for a in first.artists()}
    mix_titles = [m.title for m in first.mixes()]

    second = DeviceAgent("laptop", source=FakeSource(), data_dir=data_dir)

    assert {a.id for a in second.artists()} == artist_ids
    assert [a.name for a in second.artists()] == ["DJ Alpha"]
    assert [m.title for m in second.mixes()] == mix_titles
    assert second.device_id == first.device_id


def test_local_only_state_is_not_in_event_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    source = FakeSource()
    url = "https://example.com/local-only"
    source.bytes_by_url[url] = b"audio-bytes"
    first = DeviceAgent("laptop", source=source, data_dir=data_dir)
    mix = first.add_mix(
        title="Local set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="local-1",
        artist_name="DJ Local",
    )
    first.create_intent(
        "Plan",
        seed=1,
        device_hours=[(first.device_id, 3600)],
    )
    first.fill_caches()
    assert mix.id in {m.id for m in first.files()}

    first.set_metered(True)
    first.reject_mix(mix.id)
    assert first.is_metered() is True
    assert any(p.mix_id == mix.id for p in first.pending_rejects())
    assert first.catalog.mixes[mix.id].rejected is False

    second = DeviceAgent("laptop", source=FakeSource(), data_dir=data_dir)

    assert second.is_metered() is False
    assert second.pending_rejects() == []
    assert second.catalog.mixes[mix.id].rejected is False
    assert mix.id in {m.id for m in second.files()}
    assert second.file_bytes(mix.id) == b"audio-bytes"
