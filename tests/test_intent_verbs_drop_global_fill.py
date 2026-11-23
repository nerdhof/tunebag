"""Issue 05 (ui-actions): Switch to intent, Regenerate sequence, drop global Fill."""

from __future__ import annotations

from pathlib import Path


def _static() -> tuple[str, str, str]:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    return (
        (root / "app.js").read_text(),
        (root / "index.html").read_text(),
        (root / "app.css").read_text(),
    )


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
    js, _html, css = _static()

    set_btn = _js_function_body(js, "function setIntentPlayButton(btn, playingThis)")
    assert '"Switch to intent"' in set_btn
    assert '"Pause"' in set_btn
    assert '"Play"' not in set_btn

    # Switch to intent: always mount cover hover control (CSS shows on hover).
    cover = _js_function_body(
        js, "function renderIntentCoverStack(mixIds, { intent = null } = {})"
    )
    assert 'className = "intent-cover-action intent-play"' in cover
    assert "if (intent) {" in cover
    assert "switchToIntentFromRow(intent)" in cover
    assert "#intent-table .intent-cover-stack:hover .intent-cover-action" in css

    switch = _js_function_body(js, "async function switchToIntentFromRow(intent)")
    assert "isIntentCurrentlyPlaying(intent.id)" in switch
    assert "pausePlayback()" in switch
    assert "playIntent(intent.id)" in switch

    # Touch: right-swipe → green Switch/Pause confirm centered on name+meta block.
    assert "function bindIntentPlaySwipe(" in js
    assert "function armIntentPlaySwipe(" in js
    assert "function placeIntentPlayConfirmInBlockCenter(" in js
    assert "bindIntentPlaySwipe(nameRow, metaRow, { intent })" in js
    assert "intent-play-swipe-confirm" in css
    confirm_css = css.split("button.intent-play-swipe-confirm.symbol-btn")[1][:900]
    assert "var(--stat-tagged)" in confirm_css
    assert "translate(-100%, -50%)" in confirm_css
    assert "intent-cover-cell.intent-play-swipe-confirm-host" in css
    assert "blockRight - rightInset" in js
    assert "(blockTop + blockBottom) / 2" in js

    actions = _js_function_body(js, "function buildIntentActionButtons(intent)")
    assert "intent-play" not in actions
    assert 'setSymbolButton(regenerateBtn, BTN.refresh, "Regenerate sequence")' in actions
    assert 'setSymbolButton(fillNowBtn, BTN.fill, "Fill now")' in actions
    assert "/refresh-sequence" in actions
    assert "/fill-now" in actions
    assert 'refreshAffectedSurfaces(["intents", "cache"], { force: true })' in actions
    assert 'refreshAffectedSurfaces(["cache", "intents"], { force: true })' in actions


def test_cache_ui_has_no_global_fill() -> None:
    js, html, _css = _static()
    assert 'id="fill-btn"' not in html
    assert "Fill caches" not in html
    assert 'getElementById("fill-btn")' not in js
    assert 'fetch("/api/fill"' not in js
    # Metered + per-Intent Fill now remain.
    assert 'id="metered-toggle"' in html
    assert "/fill-now" in js
    assert "Fill now" in js


def test_switch_regenerate_fill_use_shared_refresh_path() -> None:
    js, _html, _css = _static()
    assert "async function refreshAfterIntentPlaybackMutation(" in js
    play_body = _js_function_body(js, "async function playIntent(intentId)")
    assert "refreshAfterIntentPlaybackMutation()" in play_body
    pause_body = _js_function_body(js, "async function pausePlayback()")
    assert "refreshAfterIntentPlaybackMutation({" in pause_body
    assert "markedPlayed: Boolean(data.played)" in pause_body
    helper = _js_function_body(
        js, "async function refreshAfterIntentPlaybackMutation({ markedPlayed = false } = {})"
    )
    assert "refreshPlayer()" in helper
    assert "refreshAffectedSurfaces" in helper
    assert "force: true" in helper
