"""Issue 01 (ui-actions): shared annotate control kit — UI contract."""

from __future__ import annotations

from pathlib import Path


def _static_js() -> str:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    return (root / "app.js").read_text()


def test_shared_annotate_kit_mounts_on_player_playlog_and_catalog() -> None:
    """One mountAnnotateKit entry point wires Player, Playlog, and Catalog."""
    js = _static_js()
    assert "function mountAnnotateKit(" in js
    assert 'surface: "player"' in js
    assert 'surface: "catalog"' in js
    assert 'surface: "playlog"' in js
    # Catalog Rate is interactive via the shared kit (ui-actions 03).
    catalog_start = js.index('tr.className = "mix-row"')
    catalog_end = js.index("async function refreshPlaylog")
    catalog_block = js[catalog_start:catalog_end]
    assert "mountAnnotateKit" in catalog_block
    assert "rateInteractive: true" in catalog_block
    assert "refreshAfterTag: true" in catalog_block
    # Playlog keeps interactive Rate + tag refresh via the kit.
    playlog_start = js.index("async function refreshPlaylog")
    playlog_end = js.index("async function refreshPlayerIntents")
    playlog_block = js[playlog_start:playlog_end]
    assert "mountAnnotateKit" in playlog_block
    assert "rateInteractive: true" in playlog_block
    assert "refreshAfterTag: true" in playlog_block
    assert "playlog-stars" in playlog_block
    # Player uses the same kit (no Un-reject on player chrome).
    assert "mountPlayerAnnotateKit" in js
    assert "playerAnnotateKit" in js
    assert "allowUnreject" in js
