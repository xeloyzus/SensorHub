"""Tests for the Jinja2 templates (no server/database needed)."""

from app.routers.pages import templates

LEGACY_BRAND = "nanites" + "lab"


def test_index_template_renders():
    html = templates.get_template("index.html").render()
    assert "Campus dashboard" in html
    assert LEGACY_BRAND not in html.lower()
    assert "uis campus pulse" not in html.lower()
    assert "Campus Display" in html
    assert "initDisplayPulse" in html
    assert "display-pulse.js" in html
    assert "timeSeries.js" in html
    assert "chart.js" not in html


def test_overview_template_renders():
    html = templates.get_template("overview.html").render()
    assert "Campus dashboard" in html
    assert LEGACY_BRAND not in html.lower()
    assert "uis campus pulse" not in html.lower()
    assert 'href="/overview" aria-current="page"' in html
    assert "initCampusPulse" in html
    assert "timeSeries.js" in html
    assert "data-source-badge" in html
    assert "/static/vendor/d3/d3.min.js" in html
    assert "chart.js" not in html


def test_display_template_renders():
    html = templates.get_template("display.html").render()
    assert "Campus dashboard" in html
    assert LEGACY_BRAND not in html.lower()
    assert "uis campus pulse" not in html.lower()
    assert "Campus Display" in html
    assert "initDisplayPulse" in html
    assert "display-pulse.css" in html
    assert "display-source" in html
    assert 'data-scene="local-focus"' in html
    assert 'data-scene="campus-map"' in html
    assert 'data-scene="data-quality"' in html
    assert 'data-scene="qr"' in html
    assert "chart.js" not in html


def test_mobile_template_renders():
    html = templates.get_template("mobile.html").render()
    assert "Campus dashboard" in html
    assert LEGACY_BRAND not in html.lower()
    assert "uis campus pulse" not in html.lower()
    assert "loadDashboard" in html
    assert "chart.js" not in html  # mobile page skips the chart library


def test_public_assets_do_not_expose_old_brand():
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for folder in ("templates", "static"):
        for path in (app_dir / folder).rglob("*"):
            if path.is_file():
                assert all(term not in path.read_bytes().lower() for term in (LEGACY_BRAND.encode(), b"uis campus pulse", b"demo data")), str(path)
