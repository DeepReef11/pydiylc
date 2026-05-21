"""Tests for PNG export.

These work whether pycairo is installed or not. On systems with pycairo
(typically those with a working `cairo` shared library), the tests
actually rasterize a small layout and assert the file looks like a PNG.
On systems without it, the tests verify the graceful error path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pydiylc import Project, Resistor, SolderPad
from pydiylc import cairo_render
from pydiylc import cli


def _make_project() -> Project:
    p = Project(title="png-test", width_cm=8, height_cm=6)
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(Resistor("R1", 1.0, 1.0, 1.0, 1.5, value="10K"))
    return p


def test_has_cairo_returns_bool():
    assert isinstance(cairo_render.has_cairo(), bool)


@pytest.mark.skipif(not cairo_render.has_cairo(), reason="pycairo not installed")
def test_render_png_writes_real_png(tmp_path):
    p = _make_project()
    out = tmp_path / "x.png"
    cairo_render.render_png(p, out)
    assert out.exists()
    data = out.read_bytes()
    # PNG magic header
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 200  # non-trivial content


@pytest.mark.skipif(not cairo_render.has_cairo(), reason="pycairo not installed")
def test_cli_render_png(tmp_path):
    src = tmp_path / "src.py"
    src.write_text(
        "from pydiylc import Project, Resistor\n"
        "def build():\n"
        "    p = Project(title='x')\n"
        "    p.add(Resistor('R1', 0, 0, 0, 0.5, value='10K'))\n"
        "    return p\n"
    )
    out = tmp_path / "x.png"
    rc = cli.main(["render", str(src), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.read_bytes().startswith(b"\x89PNG")


def test_render_png_raises_helpful_error_without_pycairo(monkeypatch, tmp_path):
    """When pycairo isn't importable, the error message names it."""
    import sys

    real_modules = sys.modules.copy()
    monkeypatch.setitem(sys.modules, "cairo", None)
    p = _make_project()
    with pytest.raises(ImportError, match="pycairo"):
        cairo_render.render_png(p, tmp_path / "x.png")
    sys.modules.update(real_modules)


def test_cli_render_png_exits_2_without_pycairo(tmp_path, monkeypatch, capsys):
    """The CLI should surface the missing-pycairo error gracefully."""
    import sys

    monkeypatch.setitem(sys.modules, "cairo", None)
    src = tmp_path / "src.py"
    src.write_text(
        "from pydiylc import Project, SolderPad\n"
        "project = Project()\n"
        "project.add(SolderPad('P1', x=0, y=0))\n"
    )
    out = tmp_path / "x.png"
    rc = cli.main(["render", str(src), "--out", str(out)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "pycairo" in err
