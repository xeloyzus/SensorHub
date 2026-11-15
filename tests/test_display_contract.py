"""Static contract checks for the display display system."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_display_css_uses_bounded_display_frame():
    css = (ROOT / "app/static/css/display-pulse.css").read_text()

    assert "grid-template-rows:" in css
    assert ".display-scene" in css
    assert "overflow: hidden;" in css
    assert ".display-quality-list" in css
    assert ".display-action-audiences" in css
    assert ".display-qr-panel" in css


def test_display_js_has_installation_presets_and_location_focus():
    js = (ROOT / "app/static/js/display-pulse.js").read_text()

    assert "DISPLAY_PRESETS" in js
    assert "hallway" in js
    assert "small-screen" in js
    assert "pickLocalBuilding" in js
    assert "renderDataQuality" in js
    assert "renderCampusMap" in js
    assert "display-action-audiences" in js
    assert "getSystemStatus" in js
    assert "renderDisplayUnavailable" in js
