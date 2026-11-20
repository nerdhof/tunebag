"""Issue 03 (ui-actions): Catalog Rate + annotate refresh parity — UI contracts."""

from __future__ import annotations

from pathlib import Path


def _static() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    return (root / "app.js").read_text(), (root / "index.html").read_text()


def _catalog_row_block(js: str) -> str:
    start = js.index('tr.className = "mix-row"')
    end = js.index("async function refreshPlaylog")
    return js[start:end]


def _js_function_body(js: str, signature: str) -> str:
    """Approximate source from `signature` through the next top-level async/function."""
    start = js.index(signature)
    rest = js[start + len(signature) :]
    next_fn = len(rest)
    for marker in ("\nasync function ", "\nfunction "):
        idx = rest.find(marker)
        if idx != -1:
            next_fn = min(next_fn, idx)
    return rest[:next_fn]


def test_catalog_rows_expose_interactive_rate_via_shared_kit() -> None:
    """Catalog Release rows mount the annotate kit with interactive Rate."""
    js, _html = _static()
    catalog = _catalog_row_block(js)
    assert "mountAnnotateKit" in catalog
    assert 'surface: "catalog"' in catalog
    assert "rateInteractive: true" in catalog
    assert "refreshAfterTag: true" in catalog
    # Kit onRate path posts /rate (not display-only).
    kit = _js_function_body(js, "function mountRowAnnotateKit")
    assert "/api/mixes/${mix.id}/rate" in kit
    assert "refreshAfterAnnotateMutation" in kit


def test_annotate_mutation_refreshes_catalog_history_and_player() -> None:
    """Rate/Tag from any annotate surface force-refreshes the other surfaces."""
    js, _html = _static()
    body = _js_function_body(js, "async function refreshAfterAnnotateMutation")
    assert '"mixes"' in body or "'mixes'" in body
    assert '"playlog"' in body or "'playlog'" in body
    assert "force: true" in body
    assert "refreshPlayer" in body
    # Catalog tag path opts into the same post-mutation refresh as History.
    catalog = _catalog_row_block(js)
    assert "refreshAfterTag: true" in catalog


def test_section_tips_treat_catalog_as_annotate_surface() -> None:
    """ⓘ copy matches Catalog-as-annotate (Rate/Tag/Reject) — not rate-only-on-history."""
    _js, html = _static()
    # Extract Catalog section tip.
    catalog_section = html.split('id="catalog"', 1)[1]
    tip_start = catalog_section.index('class="section-info-tip"')
    tip_end = catalog_section.index("</span>", tip_start)
    catalog_tip = catalog_section[tip_start:tip_end].lower()
    assert "rate" in catalog_tip
    assert "tag" in catalog_tip
    assert "reject" in catalog_tip
    # Must not claim rating is playlog-only.
    playlog_section = html.split('id="playlog"', 1)[1]
    playlog_tip_start = playlog_section.index('class="section-info-tip"')
    playlog_tip_end = playlog_section.index("</span>", playlog_tip_start)
    playlog_tip = playlog_section[playlog_tip_start:playlog_tip_end].lower()
    assert "rate only" not in playlog_tip
    assert "only on history" not in playlog_tip
    assert "only from history" not in catalog_tip
