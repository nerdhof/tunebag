"""Issue 05 (ui-actions): Switch to intent, Regenerate sequence, drop global Fill."""

from __future__ import annotations

from pathlib import Path


def _static() -> tuple[str, str]:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    return (root / "app.js").read_text(), (root / "index.html").read_text()


def _js_function_body(js: str, signature: str) -> str:
    start = js.index(signature)
    rest = js[start + len(signature) :]
    next_fn = len(rest)
    for marker in ("\nasync function ", "\nfunction "):
        idx = rest.find(marker)
        if idx != -1:
            next_fn = min(next_fn, idx)
    return rest[:next_fn]


def test_intent_row_verbs_match_ui_actions_glossary() -> None:
    js, _html = _static()

    set_btn = _js_function_body(js, "function setIntentPlayButton(btn, playingThis)")
    assert '"Switch to intent"' in set_btn
    assert '"Pause"' in set_btn
    assert '"Play"' not in set_btn

    # Switch to intent is on the Intent cover hover control (not the right Actions column).
    cover = _js_function_body(
        js, "function renderIntentCoverStack(mixIds, { intent = null } = {})"
    )
    assert 'className = "intent-cover-action intent-play"' in cover
    assert "switchToIntentFromRow(intent)" in cover

    switch = _js_function_body(js, "async function switchToIntentFromRow(intent)")
    assert "isIntentCurrentlyPlaying(intent.id)" in switch
    assert "pausePlayback()" in switch
    assert "playIntent(intent.id)" in switch

    actions = _js_function_body(js, "function buildIntentActionButtons(intent)")
    assert "intent-play" not in actions
    assert 'setSymbolButton(regenerateBtn, BTN.refresh, "Regenerate sequence")' in actions
    assert 'setSymbolButton(fillNowBtn, BTN.fill, "Fill now")' in actions
    assert "/refresh-sequence" in actions
    assert "/fill-now" in actions
    assert 'refreshAffectedSurfaces(["intents", "cache"], { force: true })' in actions
    assert 'refreshAffectedSurfaces(["cache", "intents"], { force: true })' in actions


def test_cache_ui_has_no_global_fill() -> None:
    js, html = _static()
    assert 'id="fill-btn"' not in html
    assert "Fill caches" not in html
    assert 'getElementById("fill-btn")' not in js
    assert 'fetch("/api/fill"' not in js
    # Metered + per-Intent Fill now remain.
    assert 'id="metered-toggle"' in html
    assert "/fill-now" in js
    assert "Fill now" in js


def test_switch_regenerate_fill_use_shared_refresh_path() -> None:
    js, _html = _static()
    assert "async function refreshAfterIntentPlaybackMutation(" in js
    play_body = _js_function_body(js, "async function playIntent(intentId)")
    assert "refreshAfterIntentPlaybackMutation()" in play_body
    pause_body = _js_function_body(js, "async function pausePlayback()")
    assert "refreshAfterIntentPlaybackMutation({ markedPlayed:" in pause_body
    helper = _js_function_body(
        js, "async function refreshAfterIntentPlaybackMutation({ markedPlayed = false } = {})"
    )
    assert "refreshPlayer()" in helper
    assert "refreshAffectedSurfaces" in helper
    assert "force: true" in helper
