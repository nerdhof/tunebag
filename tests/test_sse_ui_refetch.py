"""Issue 03 (ui-view-notices): SSE stream + UI refetch wiring."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.source import FakeSource
from tunebag.web import create_app


def _parse_sse_events(chunks: list[str]) -> list[dict]:
    """Parse SSE frames from concatenated text/event-stream chunks."""
    text = "".join(chunks)
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
        if not data_lines:
            continue
        payload = json.loads("\n".join(data_lines))
        events.append({"event": event_name, "data": payload})
    return events


def test_view_notices_sse_streams_section_after_local_write(tmp_path: Path) -> None:
    """GET /api/view-notices is text/event-stream and delivers a mixes notice."""
    agent = DeviceAgent(
        "laptop",
        source=FakeSource(),
        data_dir=tmp_path / "laptop",
    )
    client = TestClient(create_app(agent))
    chunks: list[str] = []
    done = threading.Event()
    error: list[BaseException] = []

    def read_stream() -> None:
        try:
            with client.stream("GET", "/api/view-notices") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]
                for chunk in response.iter_text():
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    if _parse_sse_events(chunks):
                        done.set()
                        break
        except BaseException as exc:  # noqa: BLE001 — surface in main thread
            error.append(exc)
            done.set()

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    # Wait briefly for the handler to subscribe before mutating.
    time.sleep(0.05)
    agent.add_mix(
        title="Set A",
        url="https://example.com/a",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
    )
    assert done.wait(timeout=2.0), "timed out waiting for SSE notice"
    assert not error, error[0]
    reader.join(timeout=1.0)

    events = _parse_sse_events(chunks)
    assert events, f"no SSE events parsed from {chunks!r}"
    notice = events[0]
    assert notice["event"] == "notice"
    assert notice["data"]["section"] == "mixes"


def test_view_notices_ui_contract_eventsource_and_section_refetch() -> None:
    """Static UI subscribes via EventSource and refetches named surfaces."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    assert 'new EventSource("/api/view-notices")' in js
    assert 'addEventListener("open"' in js or "es.onopen" in js
    assert 'addEventListener("notice"' in js
    assert "refreshMixes" in js
    assert "refreshPlaylog" in js
    assert "refreshIntents" in js
    assert "refreshPeers" in js
    assert "refreshFiles" in js
    # Add assignment refreshes peers before rendering the device picker.
    assert "Add assignment" in js
    assign_idx = js.index('setSymbolButton(assignBtn, BTN.add, "Add assignment")')
    assign_chunk = js[assign_idx : assign_idx + 450]
    assert "await refreshPeers()" in assign_chunk
    assert "refreshIntents({ force: true })" in assign_chunk
    # Cover-click expands shared sequence rows in the Intents table.
    assert "expandedIntentSequences" in js
    assert "toggleIntentSequence" in js
    assert "intent-seq-row" in js
    assert "appendIntentSequenceRows" in js
    # Section keys from the notice taxonomy
    for section in (
        "mixes",
        "playlog",
        "intents",
        "peers",
        "cache",
        "activity",
        "pairing_session",
    ):
        assert f'"{section}"' in js or f"'{section}'" in js


def _js_function_body(js: str, signature: str) -> str:
    """Return approximate source from `signature` through the next top-level async/function."""
    start = js.index(signature)
    rest = js[start + len(signature) :]
    next_fn = len(rest)
    for marker in ("\nasync function ", "\nfunction "):
        idx = rest.find(marker)
        if idx != -1:
            next_fn = min(next_fn, idx)
    return rest[:next_fn]


def test_sse_refetch_preserves_tag_editor_focus() -> None:
    """SSE/live refetch must not remount tag inputs while the listener is editing.

    force:true bypasses focusInside and clears in-progress catalog/history tags.
    Play history must also skip rebuild when focus is inside its table body.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()

    view_sections = _js_function_body(js, "async function refreshViewSections")
    assert "refreshMixes({ force: true })" not in view_sections
    assert "refreshFiles({ force: true })" not in view_sections

    all_surfaces = _js_function_body(js, "async function refreshAllViewSurfaces")
    assert "refreshMixes({ force: true })" not in all_surfaces
    assert "refreshFiles({ force: true })" not in all_surfaces

    playlog = _js_function_body(js, "async function refreshPlaylog")
    assert "focusInside(body)" in playlog


def test_cache_notice_patches_playlog_without_full_refetch() -> None:
    """CACHE-only notices refresh files and patch Playlog bars; no /api/playlog."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()

    assert "function patchPlaylogCacheFromFiles" in js
    files_now = _js_function_body(js, "async function refreshFilesNow")
    assert "patchPlaylogCacheFromFiles(data)" in files_now

    affected = _js_function_body(js, "async function refreshAffectedSurfaces")
    cache_idx = affected.index('if (wanted.has("cache"))')
    # Next sibling branch after cache (activity), or end of function.
    next_branch = affected.find("\n  if (wanted.has(", cache_idx + 1)
    cache_branch = affected[cache_idx : next_branch if next_branch != -1 else None]
    assert "await refreshFiles" in cache_branch
    assert "refreshPlaylog" not in cache_branch
