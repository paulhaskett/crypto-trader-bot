"""Static checks for browser request race protection."""

from pathlib import Path


TEMPLATES = Path(__file__).parents[1] / "src" / "templates"


def test_dynamic_pages_abort_older_get_requests():
    for name in ("dashboard.html", "models.html", "trades.html", "performance.html"):
        source = (TEMPLATES / name).read_text()
        assert "const requestControllers = {};" in source
        assert "new AbortController()" in source
        assert "requestControllers[key]?.abort()" in source
        assert "requestControllers[key] !== controller" in source or "requestControllers[key] === controller" in source
        assert "error.name === 'AbortError'" in source
