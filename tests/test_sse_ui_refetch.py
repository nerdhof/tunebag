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
    assert "refreshPlayHistory" in js
    assert "refreshIntents" in js
    assert "refreshPeers" in js
    assert "refreshFiles" in js
    # Section keys from the notice taxonomy
    for section in ("mixes", "play_history", "intents", "peers", "cache"):
        assert f'"{section}"' in js or f"'{section}'" in js
