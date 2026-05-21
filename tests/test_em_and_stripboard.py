from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pydiylc import (
    Project,
    VeroBoard,
    TraceCut,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
)


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


def test_veroboard_emits_strip_color_and_orientation():
    p = Project()
    p.add(VeroBoard("B", 1.0, 1.0, 2.0, 2.0, orientation="HORIZONTAL"))
    root = _parse(p)
    vb = root.find("components/diylc.boards.VeroBoard")
    assert vb.find("orientation").text == "HORIZONTAL"
    assert vb.find("stripColor").attrib == {"hex": "da8a67"}
    assert vb.find("spacing").attrib == {"value": "0.1", "unit": "in"}


def test_veroboard_rejects_bad_orientation():
    with pytest.raises(ValueError, match="orientation"):
        VeroBoard("B", 0, 0, 1, 1, orientation="diagonal")


def test_trace_cut_anchor_and_orientation():
    p = Project()
    p.add(TraceCut("C1", x=1.5, y=1.3, orientation="VERTICAL"))
    root = _parse(p)
    cut = root.find("components/diylc.connectivity.TraceCut")
    assert cut.find("orientation").text == "VERTICAL"
    pt = cut.find("controlPoints/point")
    assert pt.attrib == {"x": "1.5", "y": "1.3"}


def test_mini_toggle_3pdt_has_9_lugs():
    p = Project()
    p.add(MiniToggleSwitch("SW1", x=2.0, y=4.0, switch_type="_3PDT"))
    root = _parse(p)
    sw = root.find("components/diylc.electromechanical.MiniToggleSwitch")
    assert sw.find("switchType").text == "_3PDT"
    pts = sw.find("controlPoints").findall("point")
    assert len(pts) == 9


def test_mini_toggle_dpdt_has_6_lugs():
    p = Project()
    p.add(MiniToggleSwitch("SW1", x=2.0, y=4.0, switch_type="DPDT"))
    root = _parse(p)
    pts = root.find(
        "components/diylc.electromechanical.MiniToggleSwitch/controlPoints"
    ).findall("point")
    assert len(pts) == 6


def test_mini_toggle_horizontal_orientation():
    p = Project()
    p.add(
        MiniToggleSwitch("SW1", x=1.0, y=1.0, switch_type="SPST", orientation="HORIZONTAL")
    )
    root = _parse(p)
    pts = root.find(
        "components/diylc.electromechanical.MiniToggleSwitch/controlPoints"
    ).findall("point")
    # SPST = 2 lugs, horizontal → vary x
    assert pts[0].attrib == {"x": "1.0", "y": "1.0"}
    assert pts[1].attrib["x"] != pts[0].attrib["x"]
    assert pts[1].attrib["y"] == pts[0].attrib["y"]


def test_mini_toggle_rejects_bad_switch_type():
    with pytest.raises(ValueError, match="switch_type"):
        MiniToggleSwitch("SW1", x=0, y=0, switch_type="6PDT")


def test_dc_jack_polarity_default_center_negative():
    p = Project()
    p.add(PlasticDCJack("J1", x=2.0, y=1.0))
    root = _parse(p)
    j = root.find("components/diylc.electromechanical.PlasticDCJack")
    assert j.find("polarity").text == "CENTER_NEGATIVE"


def test_dc_jack_rejects_bad_polarity():
    with pytest.raises(ValueError, match="polarity"):
        PlasticDCJack("J1", x=0, y=0, polarity="center-positive")


def test_open_jack_type_and_show_labels():
    p = Project()
    p.add(OpenJack1_4("J1", x=0.5, y=2.0, type="STEREO", show_labels=False))
    root = _parse(p)
    j = root.find("components/diylc.electromechanical.OpenJack1_4")
    assert j.find("type").text == "STEREO"
    assert j.find("showLabels").text == "false"


def test_open_jack_rejects_bad_type():
    with pytest.raises(ValueError, match="OpenJack1_4.type"):
        OpenJack1_4("J1", x=0, y=0, type="TRS")


def test_full_pedal_layout_parses():
    p = Project(title="LPB-1")
    p.add(VeroBoard("B", 1.0, 1.0, 2.0, 1.7))
    p.add(TraceCut("C", x=1.4, y=1.3))
    p.add(MiniToggleSwitch("SW", x=3.0, y=2.0, switch_type="_3PDT"))
    p.add(PlasticDCJack("J_dc", x=4.0, y=1.0))
    p.add(OpenJack1_4("J_in", x=0.5, y=2.0))
    p.add(OpenJack1_4("J_out", x=4.0, y=2.0))
    _parse(p)  # must parse without error
