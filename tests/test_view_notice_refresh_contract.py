"""Issue 02 (ui-actions): View-notice + refresh contract for Activity and pairing."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.ui_notices import UIViewSection


def _agent(tmp_path: Path, *, name: str = "laptop") -> DeviceAgent:
    return DeviceAgent(
        name,
        source=FakeSource(),
        data_dir=tmp_path / name,
        player=NullPlayer(),
    )


def _sections(agent: DeviceAgent) -> list[UIViewSection]:
    return [n.section for n in agent.drain_view_notices()]


def test_note_emits_activity_notice(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.drain_view_notices()

    agent.note("fill caches start")

    assert _sections(agent) == [UIViewSection.ACTIVITY]


def test_pairing_session_mutations_emit_pairing_session_notice(tmp_path: Path) -> None:
    host = _agent(tmp_path, name="host")
    guest = _agent(tmp_path, name="guest")
    host.drain_view_notices()
    guest.drain_view_notices()

    status = host.start_pairing_session()
    assert UIViewSection.PAIRING_SESSION in _sections(host)

    pin = status["pin"]
    guest.join_pairing_session(pin=pin, host_agent=host)
    assert UIViewSection.PAIRING_SESSION in _sections(guest)
    # Guest join mutates the host session (waiting → pending_confirm).
    assert UIViewSection.PAIRING_SESSION in _sections(host)


def test_peer_ingest_still_notifies_catalog_sections(tmp_path: Path) -> None:
    """Peer Event ingest must still drive Catalog surfaces without Sync-as-reload."""
    laptop = _agent(tmp_path, name="laptop")
    phone = _agent(tmp_path, name="phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    laptop.add_mix(
        title="Set A",
        url="https://example.com/a",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
    )
    laptop.drain_view_notices()

    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    sections = set(_sections(phone))
    assert UIViewSection.MIXES in sections
    assert UIViewSection.ACTIVITY in sections


def _js_function_body(js: str, signature: str) -> str:
    start = js.index(signature)
    rest = js[start + len(signature) :]
    next_fn = len(rest)
    for marker in ("\nasync function ", "\nfunction "):
        idx = rest.find(marker)
        if idx != -1:
            next_fn = min(next_fn, idx)
    return rest[:next_fn]


def test_ui_refresh_contract_activity_pairing_and_force_path() -> None:
    """Companion: notice taxonomy, shared refresh path, polls shrink."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()

    for section in (
        "mixes",
        "playlog",
        "intents",
        "peers",
        "cache",
        "activity",
        "pairing_session",
        "player",
    ):
        assert f'"{section}"' in js or f"'{section}'" in js

    assert "async function refreshAffectedSurfaces" in js
    affected = _js_function_body(js, "async function refreshAffectedSurfaces")
    assert "force" in affected
    assert "refreshActivity" in affected
    assert "refreshPairingSession" in affected
    assert "refreshPlayer" in affected

    view_sections = _js_function_body(js, "async function refreshViewSections")
    assert "refreshAffectedSurfaces" in view_sections
    assert "force: true" not in view_sections
    assert "force:true" not in view_sections.replace(" ", "")

    after_annotate = _js_function_body(js, "async function refreshAfterAnnotateMutation")
    assert "refreshAffectedSurfaces" in after_annotate
    assert "force: true" in after_annotate

    # Activity / Player freshness are notice-driven; no standalone polls.
    assert "setInterval(refreshActivity" not in js
    assert "PLAYER_POLL_MS" not in js

    activity = _js_function_body(js, "async function refreshActivity")
    assert "refreshFiles" not in activity
    assert "/api/files" not in activity

    # Cache SSE storms coalesce: latest-wins wrapper around refreshFilesNow.
    assert "filesRefreshEpoch" in js
    assert "async function refreshFilesNow" in js
    refresh_files = _js_function_body(js, "async function refreshFiles")
    assert "filesRefreshEpoch" in refresh_files
    assert "refreshFilesNow" in refresh_files

    # Pairing poll shrinks to pending_confirm (other-device confirm), not host waiting.
    start_pair = _js_function_body(js, "async function startPairSession")
    assert "startPairPoll()" not in start_pair
    render = _js_function_body(js, "function renderPairSession")
    assert "pending_confirm" in render
    assert "startPairPoll" in render or "stopPairPoll" in render
