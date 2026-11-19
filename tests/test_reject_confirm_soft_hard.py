"""Issue 04 (ui-actions): confirm-click Reject, Soft/Hard, delayed File delete."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.reject import SOFT_REJECT_SECONDS
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
    duration_seconds: int,
    platform_id: str,
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


def test_reject_appends_event_immediately(tmp_path: Path) -> None:
    laptop, phone, source, _clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Reject now",
        duration_seconds=3600,
        platform_id="now",
        stars=Stars.FIVE,
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

    mix = laptop.catalog.mixes[mix_id]
    assert mix.rejected is True
    assert mix.rejected_at is not None
    assert mix_id in {m.id for m in laptop.files()}  # Soft: bytes still local

    phone.sync()
    assert phone.catalog.mixes[mix_id].rejected is True
    assert phone.catalog.mixes[mix_id].rejected_at == mix.rejected_at
    assert mix_id in {m.id for m in phone.files()}


def test_soft_window_keeps_file_until_hard(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Soft then hard",
        duration_seconds=3600,
        platform_id="soft-hard",
        stars=Stars.FIVE,
        audio=b"keep-then-drop",
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

    laptop.reject_mix(mix_id)
    phone.sync()
    assert mix_id in {m.id for m in laptop.files()}
    assert mix_id in {m.id for m in phone.files()}

    clock.advance(SOFT_REJECT_SECONDS - 1)
    assert laptop.commit_reject_file_deletes() == []
    assert mix_id in {m.id for m in laptop.files()}

    clock.advance(1)
    deleted = laptop.commit_reject_file_deletes()
    assert deleted == [mix_id]
    assert mix_id not in {m.id for m in laptop.files()}

    phone.commit_reject_file_deletes()
    assert mix_id not in {m.id for m in phone.files()}


def test_unreject_during_soft_keeps_file_bytes(tmp_path: Path) -> None:
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Unreject soft",
        duration_seconds=3600,
        platform_id="unrej-soft",
        stars=Stars.FIVE,
        audio=b"still-here",
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    assert mix_id in {m.id for m in laptop.files()}

    laptop.reject_mix(mix_id)
    clock.advance(30)
    laptop.un_reject_mix(mix_id)
    clock.advance(SOFT_REJECT_SECONDS)
    assert laptop.commit_reject_file_deletes() == []
    assert mix_id in {m.id for m in laptop.files()}
    assert laptop.catalog.mixes[mix_id].rejected is False
    assert laptop.catalog.mixes[mix_id].rejected_at is None


def test_unreject_after_hard_does_not_restore_bytes(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Hard unreject",
        duration_seconds=3600,
        platform_id="hard-unrej",
        stars=Stars.FIVE,
        audio=b"gone",
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

    laptop.reject_mix(mix_id)
    clock.advance(SOFT_REJECT_SECONDS)
    laptop.commit_reject_file_deletes()
    phone.sync()
    phone.commit_reject_file_deletes()
    assert mix_id not in {m.id for m in laptop.files()}

    laptop.un_reject_mix(mix_id)
    phone.sync()
    assert mix_id not in {m.id for m in laptop.files()}
    assert mix_id not in {m.id for m in phone.files()}


def test_rejected_stays_out_of_sequences(tmp_path: Path) -> None:
    laptop, _phone, source, _clock = _pair(tmp_path)
    keeper = _add_mix(
        laptop,
        source,
        title="Four star keeper",
        duration_seconds=3600,
        platform_id="four",
        tags=["techno"],
        stars=Stars.FOUR,
    )
    rejected = _add_mix(
        laptop,
        source,
        title="Rejected five",
        duration_seconds=3600,
        platform_id="rej",
        tags=["techno"],
        stars=Stars.FIVE,
    )

    laptop.reject_mix(rejected)

    intent = laptop.create_intent(
        "Techno",
        tags=["techno"],
        seed=0,
        device_hours=[(laptop.device_id, 3600)],
    )
    seq = laptop.sequence(intent.id)
    assert seq is not None
    assert [e.mix_id for e in seq.entries] == [keeper]
    assert rejected not in {e.mix_id for e in seq.entries}


def test_api_exposes_rejected_at(tmp_path: Path) -> None:
    clock = FakeClock()
    agent = DeviceAgent(
        "laptop",
        source=FakeSource(),
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    source = agent.source
    assert isinstance(source, FakeSource)
    mix_id = _add_mix(
        agent,
        source,
        title="API",
        duration_seconds=3600,
        platform_id="api-rej",
        stars=Stars.FIVE,
    )
    client = TestClient(create_app(agent))
    res = client.post(f"/api/mixes/{mix_id}/reject")
    assert res.status_code == 200
    body = res.json()
    assert body["mix"]["rejected"] is True
    assert body["mix"]["rejected_at"] is not None

    mixes = client.get("/api/mixes").json()["mixes"]
    row = next(m for m in mixes if m["id"] == str(mix_id))
    assert row["rejected"] is True
    assert row["rejected_at"] == body["mix"]["rejected_at"]
    assert "reject_pending_until" not in row


def test_ui_contract_confirm_click_soft_hard_no_undo() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert "player-undo-reject" not in html
    assert "undo-reject" not in js
    assert "reject_pending_until" not in js
    assert "bindConfirmClick" in js
    assert "really reject?" in js
    assert "isSoftRejected" in js
    assert "isHardRejected" in js
    assert "SOFT_REJECT_MS" in js
    assert "isHardRejected(mix)" in js
    assert "rejected_at" in js
