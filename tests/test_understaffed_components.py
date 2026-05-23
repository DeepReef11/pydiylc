"""Round-trip + render coverage for components that had no existing tests:
TrimmerPotentiometer, TerminalStrip, Image, BOM.
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET

from pydiylc import (
    Project,
    TrimmerPotentiometer,
    TerminalStrip,
    Image,
    BOM,
)
from pydiylc.reader import read_project
from pydiylc.svg import render_svg


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


# ---------------------------------------------------------------------------
# TrimmerPotentiometer
# ---------------------------------------------------------------------------


def test_trimmer_pot_emits_three_control_points():
    p = Project()
    p.add(TrimmerPotentiometer("T1", x=2.0, y=2.0, resistance="10K"))
    el = _parse(p).find("components/diylc.passive.TrimmerPotentiometer")
    pts = el.find("controlPoints").findall("point")
    assert len(pts) == 3


def test_trimmer_pot_resistance_round_trips(tmp_path):
    p = Project()
    p.add(TrimmerPotentiometer("T1", x=2.0, y=2.0, resistance="10K"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.components[0].resistance == "10K"


def test_trimmer_pot_renders_to_svg():
    p = Project()
    p.add(TrimmerPotentiometer("T1", x=2.0, y=2.0))
    svg = render_svg(p)
    assert 'class="trimmer"' in svg


# ---------------------------------------------------------------------------
# TerminalStrip
# ---------------------------------------------------------------------------


def test_terminal_strip_count_emits_2n_control_points():
    p = Project()
    p.add(TerminalStrip("TS1", x=1.0, y=1.0, terminal_count=4))
    el = _parse(p).find("components/diylc.boards.TerminalStrip")
    pts = el.find("controlPoints").findall("point")
    # 4 terminals × 2 rows (terminals + mounting holes) = 8
    assert len(pts) == 8


def test_terminal_strip_round_trips(tmp_path):
    p = Project()
    p.add(TerminalStrip("TS1", x=1.0, y=1.0, terminal_count=3))
    out = tmp_path / "x.diy"
    p.save(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p2 = read_project(out)
    assert isinstance(p2.components[0], TerminalStrip)
    assert p2.components[0].terminal_count == 3


def test_terminal_strip_renders_to_svg():
    p = Project()
    p.add(TerminalStrip("TS1", x=1.0, y=1.0))
    svg = render_svg(p)
    assert 'class="terminal-strip"' in svg


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------


def test_image_round_trips_data_blob(tmp_path):
    blob = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"  # tiny base64
    p = Project()
    p.add(Image("Img1", x=1.5, y=2.5, data=blob))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    img = p2.components[0]
    assert isinstance(img, Image)
    assert (img.x, img.y) == (1.5, 2.5)
    assert img.data == blob


def test_image_renders_to_svg_placeholder():
    p = Project()
    p.add(Image("Img1", x=1.5, y=2.5))
    svg = render_svg(p)
    assert 'class="image"' in svg
    assert "[image]" in svg


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


def test_bom_round_trips(tmp_path):
    p = Project()
    p.add(BOM("BOM1", x=3.0, y=4.0))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert isinstance(p2.components[0], BOM)
    assert (p2.components[0].x, p2.components[0].y) == (3.0, 4.0)


def test_bom_renders_to_svg():
    p = Project()
    p.add(BOM("BOM1", x=3.0, y=4.0))
    svg = render_svg(p)
    assert 'class="bom"' in svg


def test_understaffed_components_all_in_one_project_round_trip(tmp_path):
    """All four together — make sure no two interact badly."""
    p = Project()
    p.add(TrimmerPotentiometer("T1", x=1.0, y=1.0))
    p.add(TerminalStrip("TS1", x=2.0, y=2.0, terminal_count=3))
    p.add(Image("Img1", x=3.0, y=3.0))
    p.add(BOM("BOM1", x=4.0, y=4.0))
    out = tmp_path / "x.diy"
    p.save(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p2 = read_project(out)
    types = [type(c).__name__ for c in p2.components]
    assert types == ["TrimmerPotentiometer", "TerminalStrip", "Image", "BOM"]
