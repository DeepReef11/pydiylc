"""Tests for the SVG renderer.

These tests verify that:
- The SVG output is well-formed XML.
- Every supported component type produces something visible in the output.
- Coordinates respect inches → px scaling.
- A component that raises does not break the whole render.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pydiylc import (
    Project,
    BlankBoard,
    PerfBoard,
    VeroBoard,
    Resistor,
    RadialFilmCapacitor,
    RadialCeramicDiskCapacitor,
    RadialElectrolytic,
    PotentiometerPanel,
    DiodePlastic,
    LED,
    TransistorTO92,
    DIL_IC,
    CopperTrace,
    Jumper,
    HookupWire,
    SolderPad,
    TraceCut,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
    Label,
)
from pydiylc.svg import render_svg, render_svg_file, RenderOptions, PX_PER_INCH


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def test_empty_project_parses():
    p = Project(width_cm=10, height_cm=8)
    root = _parse(render_svg(p))
    assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_perfboard_renders_pads():
    p = Project(width_cm=10, height_cm=8)
    p.add(PerfBoard("B", 1.0, 1.0, 1.3, 1.3))
    svg = render_svg(p)
    # Should have multiple pad circles + the board rect
    assert svg.count("<circle") >= 9  # 4x4 grid = 16 pads min
    assert "<rect" in svg


def test_veroboard_renders_strips():
    p = Project(width_cm=10, height_cm=8)
    p.add(VeroBoard("B", 1.0, 1.0, 2.0, 1.5, orientation="HORIZONTAL"))
    svg = render_svg(p)
    # Strips drawn as <line> with opacity
    assert 'opacity="0.55"' in svg


def test_resistor_includes_name_label():
    p = Project()
    p.add(Resistor("R1", 1.0, 1.0, 1.0, 1.5, value="10K"))
    svg = render_svg(p)
    assert "R1" in svg or "10K" in svg
    assert "class=\"resistor\"" in svg


def test_every_component_type_emits_something():
    """Each supported component should produce a class= group."""
    p = Project(width_cm=18, height_cm=12)
    p.add(BlankBoard("BB", 0.5, 0.5, 0.8, 0.7))
    p.add(PerfBoard("PB", 1.0, 1.0, 1.3, 1.3))
    p.add(VeroBoard("VB", 1.5, 1.0, 1.8, 1.3))
    p.add(Resistor("R", 2.0, 1.0, 2.0, 1.5, value="10K"))
    p.add(RadialFilmCapacitor("Cf", 2.3, 1.0, 2.3, 1.2, value="100nF"))
    p.add(RadialCeramicDiskCapacitor("Cc", 2.6, 1.0, 2.6, 1.2, value="100pF"))
    p.add(RadialElectrolytic("Ce", 2.9, 1.0, 2.9, 1.2, value="22uF"))
    p.add(PotentiometerPanel("VR", x=3.5, y=1.5, resistance="100K"))
    p.add(DiodePlastic("D", 4.0, 1.0, 4.0, 1.2))
    p.add(LED("LED", 4.3, 1.0, 4.3, 1.2))
    p.add(TransistorTO92("Q", x=4.7, y=1.0))
    p.add(DIL_IC("U", x=5.0, y=1.0, pin_count="_8"))
    p.add(CopperTrace("T", points=[(5.5, 1.0), (5.7, 1.0)]))
    p.add(Jumper("J", 5.5, 1.2, 5.7, 1.2))
    p.add(HookupWire("W", points=[(5.5, 1.4), (5.7, 1.4)]))
    p.add(SolderPad("P", x=6.0, y=1.0))
    p.add(TraceCut("TC", x=6.2, y=1.0))
    p.add(MiniToggleSwitch("SW", x=6.5, y=1.0, switch_type="DPDT"))
    p.add(PlasticDCJack("DC", x=7.0, y=1.0))
    p.add(OpenJack1_4("AJ", x=7.5, y=1.0))
    p.add(Label("L", x=8.0, y=1.0, text="hi"))

    svg = render_svg(p)
    _parse(svg)  # valid XML

    for cls in [
        "board",
        "resistor",
        "cap-film",
        "cap-ceramic",
        "electrolytic",
        "pot",
        "diode",
        "led",
        "transistor",
        "dil",
        "trace",
        "jumper",
        "wire",
        "pad",
        "trace-cut",
        "switch",
        "dc-jack",
        "audio-jack",
        "label",
    ]:
        assert f'class="{cls}"' in svg, f"missing class: {cls}"


def test_render_options_change_dpi():
    p = Project(width_cm=10, height_cm=8)
    small = render_svg(p, RenderOptions(px_per_inch=48))
    big = render_svg(p, RenderOptions(px_per_inch=192))
    # extract width attribute
    s_root = _parse(small)
    b_root = _parse(big)
    sw = float(s_root.attrib["width"])
    bw = float(b_root.attrib["width"])
    assert bw > sw * 3


def test_grid_can_be_disabled():
    p = Project(width_cm=5, height_cm=5)
    with_grid = render_svg(p, RenderOptions(show_grid=True))
    without = render_svg(p, RenderOptions(show_grid=False))
    assert with_grid.count("<line") > without.count("<line")


def test_render_to_file(tmp_path):
    p = Project(width_cm=5, height_cm=5)
    p.add(Label("L", x=1, y=1, text="x"))
    path = tmp_path / "out.svg"
    render_svg_file(p, path)
    text = path.read_text()
    _parse(text)
    assert "<svg" in text


def test_unknown_component_does_not_break_render():
    """Custom subclass with no dedicated renderer falls back gracefully."""
    from pydiylc.components import Component

    class Weird(Component):
        name = "weird1"
        x = 1.0
        y = 1.0

        def to_xml(self, indent=4):
            return ""

    p = Project()
    p.add(Weird())
    svg = render_svg(p)
    _parse(svg)  # still parses
    # Fallback emits a dashed circle
    assert 'stroke-dasharray' in svg


def test_inch_scaling_is_correct():
    p = Project(width_cm=2.54, height_cm=2.54)  # 1 in x 1 in
    svg = render_svg(p, RenderOptions(px_per_inch=100, pad_px=0, show_grid=False))
    root = _parse(svg)
    assert abs(float(root.attrib["width"]) - 100) < 1


def test_label_alignment_propagates():
    p = Project()
    p.add(Label("L", x=1.0, y=1.0, text="x", horizontal_alignment="LEFT"))
    svg = render_svg(p)
    assert 'text-anchor="start"' in svg


# ---------------------------------------------------------------------------
# Regressions: wire point counts, alpha scale, colors, inverted corners
# ---------------------------------------------------------------------------


def test_three_five_seven_point_wires_render():
    """Every legal WIRE_POINT_COUNT renders a path — 3/5/7 used to crash the
    4-point unpack and disappear from the output."""
    from pydiylc import HookupWire, CurvedTrace

    shapes = {
        "THREE": [(1, 1), (2, 2), (3, 1)],
        "FIVE": [(1, 1), (1.5, 2), (2, 1), (2.5, 2), (3, 1)],
        "SEVEN": [(1, 1), (1.3, 2), (1.6, 1), (2, 2), (2.4, 1), (2.7, 2), (3, 1)],
    }
    for count, pts in shapes.items():
        p = Project()
        p.add(HookupWire("W", points=pts, point_count=count))
        p.add(CurvedTrace("T", points=pts, point_count=count))
        svg = render_svg(p)
        assert "error rendering" not in svg, f"{count}: renderer raised"
        assert 'class="wire"' in svg
        assert 'class="curved-trace"' in svg


def test_alpha_uses_diylc_127_scale():
    """DIYLC's max alpha is 127 (fully opaque) — dividing by 255 rendered
    everything at half its intended opacity."""
    from pydiylc import EllipticalCutout

    p = Project()
    p.add(EllipticalCutout("E", x1=1, y1=1, x2=2, y2=2, alpha=127))
    assert 'fill-opacity="1.00"' in render_svg(p)


def test_hash_prefixed_colors_do_not_double_hash():
    """Colors are normalized through _color() everywhere — '#ff0000' used to
    emit '##ff0000' in renderers that interpolated the raw field."""
    from pydiylc import Polygon

    p = Project()
    p.add(Polygon("P", points=[(1, 1), (2, 1), (2, 2)],
                  color="#ff0000", border_color="#00ff00"))
    svg = render_svg(p)
    assert "##" not in svg
    assert "#ff0000" in svg


def test_inverted_corner_boards_render_positive_rects():
    """Swapped corners must not emit negative-width/height rects (invalid
    SVG — conforming viewers drop the element)."""
    from pydiylc import EyeletBoard, MarshallPerfBoard, TriPadBoard

    p = Project()
    p.add(EyeletBoard("B1", x1=2, y1=2, x2=1, y2=1))
    p.add(MarshallPerfBoard("B2", x1=4, y1=2, x2=3, y2=1))
    p.add(TriPadBoard("B3", x1=6, y1=2, x2=5, y2=1))
    svg = render_svg(p)
    assert 'width="-' not in svg
    assert 'height="-' not in svg


def test_two_point_curved_trace_honors_size():
    from pydiylc import CurvedTrace
    from pydiylc.core import mm
    import re

    p = Project()
    p.add(CurvedTrace("T", points=[(1, 1), (2, 1)], size=mm(2.0),
                      point_count="TWO"))
    svg = render_svg(p)
    m = re.search(r'class="curved-trace".*?stroke-width="([\d.]+)"', svg)
    assert m and abs(float(m.group(1)) - (2.0 / 25.4) * 96) < 0.2
