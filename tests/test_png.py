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


@pytest.mark.skipif(not cairo_render.has_cairo(), reason="pycairo not installed")
def test_nonstandard_wire_point_counts_draw_ink(tmp_path):
    """3/5/7-point wires must draw — the 4-point unpack used to raise and the
    per-component guard swallowed it, leaving a blank spot."""
    import cairo

    from pydiylc import Project, HookupWire

    p = Project()
    p.add(HookupWire("W", points=[(1, 1), (2, 2), (3, 1)], point_count="THREE"))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 500, 400)
    cairo_render.draw_project(cairo.Context(surf), p, show_grid=False)
    buf = surf.get_data()
    ink = sum(1 for i in range(0, len(buf), 4) if buf[i + 2] < 200 and buf[i + 3] > 200)
    assert ink > 50


@pytest.mark.skipif(not cairo_render.has_cairo(), reason="pycairo not installed")
def test_vertical_inductor_bumps_follow_the_wire(tmp_path):
    """Cairo used to draw coil scallops at fixed world angles — a vertical
    inductor got sideways bumps and stray chords. The ink must hug the wire."""
    import cairo

    from pydiylc import Project, InductorSymbol

    p = Project()
    p.add(InductorSymbol("L1", x1=1.0, y1=1.0, x2=1.0, y2=2.0))
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 400)
    cairo_render.draw_project(cairo.Context(surf), p, show_grid=False)
    buf = surf.get_data()
    W = surf.get_width()
    xs = [
        xx
        for yy in range(90, 200)
        for xx in range(20, 300)
        if buf[(yy * W + xx) * 4 + 2] < 200 and buf[(yy * W + xx) * 4 + 3] > 200
    ]
    assert xs, "no inductor ink found"
    assert max(xs) - min(xs) < 40  # bump diameter, not sideways scallops
