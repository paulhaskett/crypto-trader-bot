"""Static and runtime checks for browser HTML escaping."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_shared_escape_helper_is_loaded_by_dynamic_pages():
    helper = ROOT / "src" / "static" / "js" / "render.js"
    source = helper.read_text()
    assert "window.escapeHtml" in source
    assert "&lt;" in source
    for name in ("dashboard.html", "models.html", "trades.html", "performance.html"):
        page = (ROOT / "src" / "templates" / name).read_text()
        assert '/static/js/render.js' in page


def test_dynamic_text_sites_use_escape_helper():
    for name in ("models.html", "trades.html"):
        page = (ROOT / "src" / "templates" / name).read_text()
        assert "escapeHtml(" in page
