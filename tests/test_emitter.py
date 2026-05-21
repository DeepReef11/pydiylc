from __future__ import annotations

import xml.etree.ElementTree as ET

from pydiylc import (
    Project,
    PerfBoard,
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    CopperTrace,
    Jumper,
    HookupWire,
    SolderPad,
    Label,
)


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


def test_empty_project_parses():
    p = Project()
    root = _parse(p)
    assert root.tag == "project"
    assert root.find("fileVersion/major").text == "5"
    assert root.find("components") is not None


def test_resistor_value_split_and_attrs():
    p = Project()
    p.add(Resistor("R1", 1.0, 1.0, 1.0, 1.5, value="4.7K"))
    root = _parse(p)
    r = root.find("components/diylc.passive.Resistor")
    assert r.find("name").text == "R1"
    v = r.find("value")
    assert v.attrib == {"value": "4.7", "unit": "K"}
    pts = r.find("points").findall("point")
    assert len(pts) == 3  # p1, p2, mid
    assert pts[2].attrib == {"x": "1.0", "y": "1.25"}


def test_capacitor_default_unit_picks_nf():
    p = Project()
    p.add(RadialFilmCapacitor("C1", 0, 0, 0, 0.1, value="100"))  # bare
    root = _parse(p)
    v = root.find("components/diylc.passive.RadialFilmCapacitor/value")
    assert v.attrib == {"value": "100.0", "unit": "nF"}


def test_electrolytic_polarized_default():
    p = Project()
    p.add(RadialElectrolytic("C1", 0, 0, 0, 0.1, value="22uF"))
    root = _parse(p)
    e = root.find("components/diylc.passive.RadialElectrolytic")
    assert e.find("polarized").text == "true"
    assert e.find("value").attrib == {"value": "22.0", "unit": "uF"}


def test_copper_trace_midpoint_added_for_2_points():
    p = Project()
    p.add(CopperTrace("T1", points=[(1.0, 1.0), (2.0, 1.0)]))
    root = _parse(p)
    pts = root.find("components/diylc.connectivity.CopperTrace/points").findall("point")
    assert len(pts) == 3
    assert pts[2].attrib == {"x": "1.5", "y": "1.0"}


def test_hookup_wire_2_to_4_interpolation():
    p = Project()
    p.add(HookupWire("W1", points=[(0.0, 0.0), (3.0, 0.0)], color="ff0000"))
    root = _parse(p)
    cps = root.find("components/diylc.connectivity.HookupWire/controlPoints2").findall("point")
    assert len(cps) == 4
    assert cps[1].attrib["x"] == "1.0"
    assert cps[2].attrib["x"] == "2.0"


def test_solder_pad_and_label():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(Label("L1", x=1.0, y=2.0, text="ground & power"))
    root = _parse(p)
    pad = root.find("components/diylc.connectivity.SolderPad")
    assert pad.find("point").attrib == {"x": "1.0", "y": "1.0"}
    lbl = root.find("components/diylc.misc.Label")
    assert lbl.find("text").text == "ground & power"


def test_perfboard_default_palette():
    p = Project()
    p.add(PerfBoard("Board1", x1=1.0, y1=1.0, x2=2.0, y2=1.7))
    root = _parse(p)
    pb = root.find("components/diylc.boards.PerfBoard")
    assert pb.find("boardColor").attrib == {"hex": "f8ebb3"}
    assert pb.find("spacing").attrib == {"value": "0.1", "unit": "in"}


def test_jumper_attrs():
    p = Project()
    p.add(Jumper("J1", 1.0, 1.0, 1.0, 1.5, color="ff8800"))
    root = _parse(p)
    j = root.find("components/diylc.connectivity.Jumper")
    assert j.find("color").attrib == {"hex": "ff8800"}
    assert j.find("style").text == "SOLID"


def test_save_round_trip(tmp_path):
    p = Project(title="rt")
    p.add(SolderPad("P1", x=0.1, y=0.1))
    out = p.save(tmp_path / "rt.diy")
    txt = out.read_text()
    assert txt.startswith("<?xml")
    ET.fromstring(txt)  # must parse


def test_hex_color_short_form():
    p = Project()
    p.add(SolderPad("P1", x=0, y=0, color="abc"))
    root = _parse(p)
    pad = root.find("components/diylc.connectivity.SolderPad")
    assert pad.find("color").attrib == {"hex": "aabbcc"}
