"""Static accessibility and responsive-layout checks for GUI templates."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "src" / "templates"


def test_navigation_toggles_have_accessible_names():
    for name in ("dashboard.html", "models.html", "trades.html", "performance.html", "settings.html"):
        source = (TEMPLATES / name).read_text()
        assert 'aria-label="Toggle navigation"' in source
        assert 'aria-controls="navbarNav"' in source


def test_shared_stylesheet_provides_focus_touch_and_reduced_motion_rules():
    css = (ROOT / "src" / "static" / "style.css").read_text()
    assert "min-height: 44px" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    for name in ("dashboard.html", "models.html", "trades.html", "performance.html", "settings.html"):
        assert '/static/style.css' in (TEMPLATES / name).read_text()


def test_icon_only_dashboard_controls_have_labels():
    source = (TEMPLATES / "dashboard.html").read_text()
    assert 'aria-label="Refresh exchange rate"' in source
    assert 'aria-label="Close ${escapeHtml' in source
