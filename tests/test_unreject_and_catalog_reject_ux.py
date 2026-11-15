"""Issue 02 (play-history): Un-reject LWW + Catalog reject UX via DeviceAgent / HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.reject import UNDO_SECONDS
from tunebag.source import FakeSource
from tunebag.web import create_app


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        clock=clk,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        clock=clk,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
    duration_seconds: int = 3600,
    tags: list[str] | None = None,
    stars: Stars | None = None,
    audio: bytes | None = None,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = audio if audio is not None else f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    if tags is not None:
        agent.tag_mix(mix.id, tags)
    if stars is not None:
        agent.rate_mix(mix.id, stars)
    return mix.id


def test_unreject_clears_reject_and_mix_reenters_sequence(tmp_path: Path) -> None:
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Come back",
        platform_id="come-back",
        tags=["techno"],
        stars=Stars.FIVE,
    )

    laptop.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()
    assert laptop.catalog.mixes[mix_id].rejected is True

    laptop.un_reject_mix(mix_id)
    assert laptop.catalog.mixes[mix_id].rejected is False

    intent = laptop.create_intent(
        "Techno",
        tags=["techno"],
        seed=0,
        device_hours=[(laptop.device_id, 3600)],
    )
    seq = laptop.sequence(intent.id)
    assert seq is not None
    assert mix_id in {e.mix_id for e in seq.entries}


def test_newer_unreject_beats_older_reject_across_peers(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Race", platform_id="race", stars=Stars.FIVE)
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()

    clock.advance(30)
    # Phone rejects too (so it can later un-reject after meeting), then both meet;
    # phone's later Un-reject must win over laptop's older Reject.
    phone.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    phone.commit_pending_rejects()
    clock.advance(1)
    phone.un_reject_mix(mix_id)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.catalog.mixes[mix_id].rejected is False
    assert phone.catalog.mixes[mix_id].rejected is False


def test_newer_reject_beats_older_unreject_across_peers(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Race2", platform_id="race2", stars=Stars.FIVE)
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()
    clock.advance(1)
    laptop.un_reject_mix(mix_id)

    clock.advance(30)
    phone.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    phone.commit_pending_rejects()

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.catalog.mixes[mix_id].rejected is True
    assert phone.catalog.mixes[mix_id].rejected is True


def test_unreject_does_not_restore_file_bytes(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="No refill",
        platform_id="no-refill",
        stars=Stars.FIVE,
        audio=b"bytes-on-disk",
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    assert mix_id in {m.id for m in laptop.files()}

    laptop.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()
    phone.sync()
    assert mix_id not in {m.id for m in laptop.files()}
    assert mix_id not in {m.id for m in phone.files()}

    laptop.un_reject_mix(mix_id)
    phone.sync()

    assert mix_id not in {m.id for m in laptop.files()}
    assert mix_id not in {m.id for m in phone.files()}


def test_catalog_reject_uses_same_pending_undo_window(tmp_path: Path) -> None:
    """Catalog reject shares reject_mix — local until commit, undo cancels."""
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Catalog reject",
        platform_id="catalog-rej",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[(phone.device_id, 3600), (laptop.device_id, 3600)],
    )
    phone.sync()
    laptop.fill_caches()

    laptop.reject_mix(mix_id)
    assert laptop.catalog.mixes[mix_id].rejected is False
    assert any(p.mix_id == mix_id for p in laptop.pending_rejects())
    phone.sync()
    assert phone.catalog.mixes[mix_id].rejected is False

    assert laptop.undo_reject(mix_id) is True
    clock.advance(UNDO_SECONDS)
    assert laptop.commit_pending_rejects() == []
    assert laptop.catalog.mixes[mix_id].rejected is False


def test_artists_api_includes_rejected_mix_count(tmp_path: Path) -> None:
    source = FakeSource()
    clock = FakeClock()
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    kept = _add_mix(agent, source, title="Kept", platform_id="kept", stars=Stars.FOUR)
    rejected = _add_mix(
        agent, source, title="Rejected", platform_id="rej", stars=Stars.FIVE
    )
    agent.reject_mix(rejected)
    clock.advance(UNDO_SECONDS)
    agent.commit_pending_rejects()
    rejected_artist_id = str(agent.catalog.mixes[rejected].artist_id)
    kept_artist_id = str(agent.catalog.mixes[kept].artist_id)

    client = TestClient(create_app(agent))
    res = client.get("/api/artists")
    assert res.status_code == 200
    by_id = {a["id"]: a for a in res.json()["artists"]}
    assert by_id[rejected_artist_id]["rejected_mixes"] == 1
    assert by_id[rejected_artist_id]["mixes"] == 1
    assert by_id[kept_artist_id]["rejected_mixes"] == 0
    assert by_id[kept_artist_id]["mixes"] == 1


def test_catalog_ui_contract_has_rejected_filter_and_unreject() -> None:
    """Static Catalog surface exposes Rejected filter + Un-reject action hooks."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="catalog-show-rejected"' in html
    assert "showRejectedCatalog" in js
    assert "mix-rejected" in js
    assert "/api/mixes/${mix.id}/un-reject" in js
    assert "${rejected} rejected" in js


def test_unreject_api_clears_committed_reject(tmp_path: Path) -> None:
    source = FakeSource()
    clock = FakeClock()
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    mix_id = _add_mix(agent, source, title="API", platform_id="api", stars=Stars.FIVE)
    agent.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    agent.commit_pending_rejects()
    client = TestClient(create_app(agent))

    res = client.post(f"/api/mixes/{mix_id}/un-reject")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["mix"]["rejected"] is False
    assert agent.catalog.mixes[mix_id].rejected is False
