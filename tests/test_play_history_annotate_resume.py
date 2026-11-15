"""Issue 03 (play-history): annotate + resume — DeviceAgent/HTTP + UI contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.web import create_app


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _RecordingPlayer(NullPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.plays: list[tuple[Path, float]] = []

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        super().play(path, start_seconds=start_seconds)
        self.plays.append((path, start_seconds))


def _pair(
    tmp_path: Path,
    *,
    player: NullPlayer | None = None,
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=player if player is not None else NullPlayer(),
        clock=clk,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        player=NullPlayer(),
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
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    return mix.id


def _play_ready(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
) -> tuple[UUID, UUID]:
    mix_id = _add_mix(
        agent,
        source,
        title=title,
        duration_seconds=duration_seconds,
        platform_id=platform_id,
    )
    agent.rate_mix(mix_id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, duration_seconds)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix_id)
    return mix_id, intent.id


def test_http_play_with_mix_id_resumes_at_catalog_playhead(tmp_path: Path) -> None:
    """POST /api/player/play with mix_id starts at the Catalog Playhead."""
    recorder = _RecordingPlayer()
    laptop, _phone, source, _clock = _pair(tmp_path, player=recorder)
    mix_id, intent_id = _play_ready(
        laptop,
        source,
        title="Resume me",
        duration_seconds=3600,
        platform_id="resume",
    )
    laptop.report_playhead(900)
    laptop.stop()
    recorder.plays.clear()
    client = TestClient(create_app(laptop))

    res = client.post(
        "/api/player/play",
        json={"intent_id": str(intent_id), "mix_id": str(mix_id)},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["playing"] is True
    assert body["mix"]["id"] == str(mix_id)
    assert laptop.playback_position() == pytest.approx(900, abs=0.05)
    assert len(recorder.plays) == 1
    assert recorder.plays[0][1] == pytest.approx(900, abs=0.05)


def test_play_history_ui_contract_rejected_filter_and_reject_pipeline() -> None:
    """Static Play history exposes Rejected filter + reject/undo/un-reject hooks."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="play-history-show-rejected"' in html
    assert "showRejectedHistory" in js
    assert "history-reject" in js
    assert "history-undo-reject" in js
    assert "history-un-reject" in js
    assert "/api/mixes/${mix.id}/reject" in js
    assert "/api/mixes/${mix.id}/undo-reject" in js
    assert "/api/mixes/${mix.id}/un-reject" in js
    assert "mix-rejected" in js
    # Default filter hides rejected when showRejectedHistory is false
    assert "showRejectedHistory" in js
    assert "!mix.rejected" in js or "mix.rejected" in js


def test_play_history_ui_contract_rate_tag_and_resume() -> None:
    """Static Play history wires Rate, Tag, and Resume at playhead."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert "history-rate" in js or "history-stars" in js
    assert "/api/mixes/${mix.id}/rate" in js
    assert "history-tag" in js or "history-tags" in js
    assert "/api/mixes/${mix.id}/tags" in js
    assert "history-resume" in js
    assert 'mix_id:' in js or '"mix_id"' in js
    # Resume posts play with mix_id
    assert "/api/player/play" in js
    assert "mix_id" in js
    # Columns / tip mention annotate + resume
    assert "Rating" in html or "Rate" in html
    assert "resume" in html.lower() or "Resume" in html


def test_catalog_ui_contract_rating_remains_display_only() -> None:
    """Catalog mix rows show stars as text; rating edits stay off Catalog."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    # Catalog rating cell is text (stars★ or —), not a /rate fetch in mix-row builder
    assert '${mix.stars}★' in js or "${mix.stars}★" in js
    # Player and History may rate; Catalog refreshMixes must not POST /rate
    # Isolate the catalog row builder region roughly between mix-row and refreshPlayHistory
    catalog_start = js.index('tr.className = "mix-row"')
    catalog_end = js.index("async function refreshPlayHistory")
    catalog_block = js[catalog_start:catalog_end]
    assert "/rate" not in catalog_block
    assert "player-stars" in js
