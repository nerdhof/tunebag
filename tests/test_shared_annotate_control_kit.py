"""Issue 01 (ui-actions): shared annotate control kit — UI contract."""

from __future__ import annotations

from pathlib import Path


def _static_js() -> str:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    return (root / "app.js").read_text()


def test_shared_annotate_kit_mounts_on_player_history_and_catalog() -> None:
    """One mountAnnotateKit entry point wires Player, History, and Catalog."""
    js = _static_js()
    assert "function mountAnnotateKit(" in js
    assert 'surface: "player"' in js
    assert 'surface: "catalog"' in js
    assert 'surface: "history"' in js
    # Catalog stays display-only for Rate until ticket 03.
    catalog_start = js.index('tr.className = "mix-row"')
    catalog_end = js.index("async function refreshPlayHistory")
    catalog_block = js[catalog_start:catalog_end]
    assert "mountAnnotateKit" in catalog_block
    assert "rateInteractive: false" in catalog_block
    assert "interactive: false" in catalog_block
    assert "/rate" not in catalog_block
    # History keeps interactive Rate + tag refresh via the kit.
    history_start = js.index("async function refreshPlayHistory")
    history_end = js.index("async function refreshPlayerIntents")
    history_block = js[history_start:history_end]
    assert "mountAnnotateKit" in history_block
    assert "rateInteractive: true" in history_block
    assert "refreshAfterTag: true" in history_block
    assert "history-stars" in history_block
    # Player uses the same kit (no Un-reject on player chrome).
    assert "mountPlayerAnnotateKit" in js
    assert "playerAnnotateKit" in js
    assert "allowUnreject" in js
