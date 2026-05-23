"""Tests for the viewer and Cairo backend.

These run on hosts WITHOUT GTK or pycairo installed. The viewer module must
import cleanly; show()/main() raise a clear ImportError when GTK isn't there;
loaders work without any UI bits.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pydiylc import Project, Resistor, viewer
from pydiylc import cairo_render


# ---------------------------------------------------------------------------
# Cairo backend
# ---------------------------------------------------------------------------


def test_cairo_has_renderer_for_every_component():
    """The Cairo renderer dispatch table covers the same set as SVG."""
    from pydiylc.components import ALL_COMPONENTS

    missing = [
        c.__name__ for c in ALL_COMPONENTS if c not in cairo_render._RENDERERS
    ]
    assert not missing, f"Cairo backend missing: {missing}"


def test_svg_has_renderer_for_every_component():
    """The SVG renderer dispatch covers every component too.

    Without this, new components silently render as the gray fallback dot
    in browser previews, MCP-served renders, and CLI exports.
    """
    from pydiylc.components import ALL_COMPONENTS
    from pydiylc import svg

    missing = [
        c.__name__ for c in ALL_COMPONENTS if c not in svg._RENDERERS
    ]
    assert not missing, f"SVG backend missing: {missing}"


def test_hex_to_rgb_short_form():
    r, g, b = cairo_render._hex_to_rgb("abc")
    assert abs(r - 0xAA / 255) < 1e-6
    assert abs(g - 0xBB / 255) < 1e-6
    assert abs(b - 0xCC / 255) < 1e-6


def test_hit_test_finds_component():
    """Without rendering, just exercise the geometry."""
    p = Project()
    p.add(Resistor("R1", 1.0, 1.0, 1.0, 1.5))
    # 1.0 in * 96 = 96 px, midpoint at y=1.25 -> 120 px
    hit = cairo_render.hit_test(p, 96, 120, cairo_render.PX_PER_INCH)
    assert hit is not None and hit.name == "R1"
    miss = cairo_render.hit_test(p, 0, 0, cairo_render.PX_PER_INCH)
    assert miss is None


def test_hit_test_returns_topmost():
    """Later-added components are drawn on top, so should hit first."""
    p = Project()
    p.add(Resistor("R_under", 1.0, 1.0, 1.0, 1.5))
    p.add(Resistor("R_over", 1.0, 1.0, 1.0, 1.5))
    hit = cairo_render.hit_test(p, 96, 120, cairo_render.PX_PER_INCH)
    assert hit.name == "R_over"


def test_component_bbox_handles_all_shapes():
    from pydiylc import (
        Project, PerfBoard, SolderPad, CopperTrace, TransistorTO92,
        Label, HookupWire,
    )

    p = Project()
    p.add(PerfBoard("B", 1.0, 1.0, 2.0, 2.0))
    p.add(SolderPad("Pad", x=1.5, y=1.5))
    p.add(CopperTrace("T", points=[(1.0, 1.0), (2.0, 1.0)]))
    p.add(TransistorTO92("Q", x=1.5, y=1.5))
    p.add(Label("L", x=0.5, y=0.5, text="x"))
    p.add(HookupWire("W", points=[(0.0, 0.0), (3.0, 3.0)]))

    for c in p.components:
        bbox = cairo_render._component_bbox(c, cairo_render.PX_PER_INCH)
        assert bbox is not None, f"no bbox for {type(c).__name__}"
        x1, y1, x2, y2 = bbox
        assert x2 >= x1 and y2 >= y1


# ---------------------------------------------------------------------------
# Loaders (no GUI needed)
# ---------------------------------------------------------------------------


def test_load_python_with_project_attr(tmp_path):
    src = tmp_path / "layout.py"
    src.write_text(
        "from pydiylc import Project, Resistor\n"
        "project = Project(title='py')\n"
        "project.add(Resistor('R1', 0, 0, 0, 0.5, value='10K'))\n"
    )
    project, builder = viewer.load(src)
    assert project.title == "py"
    assert len(project.components) == 1
    # builder rebuilds fresh
    p2 = builder()
    assert p2.title == "py"
    assert p2 is not project  # different instance


def test_load_python_with_build_func(tmp_path):
    src = tmp_path / "layout.py"
    src.write_text(
        "from pydiylc import Project\n"
        "def build():\n"
        "    return Project(title='built')\n"
    )
    project, _ = viewer.load(src)
    assert project.title == "built"


def test_load_python_missing_project_raises(tmp_path):
    src = tmp_path / "layout.py"
    src.write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="define a top-level"):
        viewer.load(src)


def test_load_json(tmp_path):
    src = tmp_path / "layout.json"
    src.write_text(
        json.dumps(
            {
                "title": "jsontest",
                "components": [
                    {"type": "Resistor", "name": "R1", "x1": 0, "y1": 0,
                     "x2": 0, "y2": 0.5, "value": "10K"},
                ],
            }
        )
    )
    project, _ = viewer.load(src)
    assert project.title == "jsontest"


def test_load_diy_now_works(tmp_path):
    """Once the reader landed, viewer.load() accepts .diy files."""
    from pydiylc import Project, Resistor

    out = tmp_path / "layout.diy"
    p = Project(title="from-diy")
    p.add(Resistor("R1", 0, 0, 0, 0.5, value="10K"))
    p.save(out)
    project, builder = viewer.load(out)
    assert project.title == "from-diy"
    assert len(project.components) == 1
    # builder re-reads
    p2 = builder()
    assert p2.title == "from-diy"


def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        viewer.load(tmp_path / "nope.py")


def test_load_unknown_extension(tmp_path):
    src = tmp_path / "x.xml"
    src.write_text("")
    with pytest.raises(ValueError):
        viewer.load(src)


# ---------------------------------------------------------------------------
# GTK availability + CLI
# ---------------------------------------------------------------------------


def test_has_gtk_does_not_raise():
    """Should return bool, never crash."""
    result = viewer.has_gtk()
    assert isinstance(result, bool)


def test_show_raises_helpful_error_without_gtk():
    if viewer.has_gtk():
        pytest.skip("GTK is installed; this test only meaningful without it")
    p = Project()
    with pytest.raises(ImportError, match="GTK 4"):
        viewer.show(p)


def test_cli_check_returns_status():
    """`pydiylc-view --check` should not crash and should print availability."""
    proc = subprocess.run(
        [sys.executable, "-m", "pydiylc.viewer", "--check"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Exit code = 0 if GTK available, 1 if not. Either is fine.
    assert proc.returncode in (0, 1)
    assert "GTK 4" in proc.stdout


def test_cli_main_help_returns_2():
    """No args → help is printed and exit code is 2."""
    rc = viewer.main([])
    assert rc == 2
