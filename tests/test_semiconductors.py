from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pydiylc import (
    Project,
    DiodePlastic,
    LED,
    TransistorTO92,
    DIL_IC,
    PotentiometerPanel,
)


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


def test_diode_plastic_has_marker_color():
    p = Project()
    p.add(DiodePlastic("D1", 1.0, 1.0, 1.0, 1.2, value="1N4148"))
    root = _parse(p)
    d = root.find("components/diylc.semiconductors.DiodePlastic")
    assert d.find("markerColor").attrib == {"hex": "dddddd"}
    assert d.find("value").text == "1N4148"


def test_led_has_hide_short_leads():
    p = Project()
    p.add(LED("LED1", 1.0, 1.0, 1.0, 1.2, hide_short_leads=True))
    root = _parse(p)
    l = root.find("components/diylc.semiconductors.LED")
    assert l.find("hideShortLeads").text == "true"


def test_transistor_to92_three_control_points_default_orientation():
    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=1.5, value="2N5088"))
    root = _parse(p)
    q = root.find("components/diylc.semiconductors.TransistorTO92")
    pts = q.find("controlPoints").findall("point")
    assert len(pts) == 3
    # DEFAULT orientation = pins go down the Y axis, 0.1 in apart
    assert pts[0].attrib == {"x": "2.0", "y": "1.5"}
    assert pts[1].attrib == {"x": "2.0", "y": "1.6"}
    assert pts[2].attrib == {"x": "2.0", "y": "1.7"}
    assert q.find("pinout").text == "BJT_EBC"


def test_transistor_to92_rotated():
    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=1.5, orientation="_270"))
    root = _parse(p)
    pts = root.find("components/diylc.semiconductors.TransistorTO92/controlPoints").findall("point")
    # _270: pins extend in +X
    assert pts[0].attrib["x"] == "2.0"
    assert pts[1].attrib["x"] == "2.1"
    assert pts[2].attrib["x"] == "2.2"


def test_transistor_to92_rejects_bad_pinout():
    with pytest.raises(ValueError, match="pinout"):
        TransistorTO92("Q1", x=1.0, y=1.0, pinout="EBC")


def test_dil_ic_pin_count_enum():
    p = Project()
    p.add(DIL_IC("U1", x=2.0, y=1.5, value="TL072", pin_count="_8"))
    root = _parse(p)
    u = root.find("components/diylc.semiconductors.DIL_IC")
    assert u.find("pinCount").text == "_8"
    assert u.find("rowSpacing").attrib == {"value": "0.3", "unit": "in"}


def test_dil_ic_rejects_odd_pin_count():
    with pytest.raises(ValueError, match="pin_count"):
        DIL_IC("U1", x=0, y=0, pin_count="_7")


def test_pot_panel_three_lugs_default():
    p = Project()
    p.add(PotentiometerPanel("VR1", x=2.0, y=4.0, resistance="100K", taper="LOG"))
    root = _parse(p)
    pot = root.find("components/diylc.passive.PotentiometerPanel")
    pts = pot.find("controlPoints").findall("point")
    assert len(pts) == 3
    # DEFAULT (horizontal, right-to-left from the anchor)
    assert pts[0].attrib == {"x": "2.0", "y": "4.0"}
    assert pts[1].attrib == {"x": "1.8", "y": "4.0"}
    assert pts[2].attrib == {"x": "1.6", "y": "4.0"}
    assert pot.find("resistance").attrib == {"value": "100.0", "unit": "K"}
    assert pot.find("taper").text == "LOG"


def test_pot_panel_rejects_bad_taper():
    with pytest.raises(ValueError, match="taper"):
        PotentiometerPanel("VR1", x=0, y=0, taper="logarithmic")


def test_pot_panel_resistance_default_unit():
    p = Project()
    p.add(PotentiometerPanel("VR1", x=0, y=0, resistance="500"))  # bare
    root = _parse(p)
    r = root.find("components/diylc.passive.PotentiometerPanel/resistance")
    assert r.attrib == {"value": "500.0", "unit": "K"}
