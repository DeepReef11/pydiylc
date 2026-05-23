"""Tests for the schematic symbols + CurvedTrace added in v0.1.0."""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pydiylc import (
    Project,
    ResistorSymbol,
    CapacitorSymbol,
    DiodeSymbol,
    BJTSymbol,
    GroundSymbol,
    CurvedTrace,
)
from pydiylc.reader import read_project


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


def test_resistor_symbol_value_round_trips_as_string(tmp_path):
    p = Project()
    p.add(ResistorSymbol("R1", 1.0, 1.0, 1.0, 1.5, value="470K"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.components[0].value == "470K"


def test_capacitor_symbol_polarized_default_false():
    p = Project()
    p.add(CapacitorSymbol("C1", 1.0, 1.0, 1.0, 1.5))
    el = _parse(p).find("components/diylc.passive.CapacitorSymbol")
    assert el.find("polarized").text == "false"


def test_diode_symbol_value_as_string(tmp_path):
    p = Project()
    p.add(DiodeSymbol("D1", 1.0, 1.0, 1.0, 1.5, value="1N4148"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.components[0].value == "1N4148"


def test_bjt_symbol_emits_polarity_and_4_control_points():
    p = Project()
    p.add(BJTSymbol("Q1", x=2.0, y=2.0, polarity="PNP", value="2N3906"))
    el = _parse(p).find("components/diylc.semiconductors.BJTSymbol")
    assert el.find("polarity").text == "PNP"
    pts = el.find("controlPoints").findall("point")
    assert len(pts) == 4


def test_bjt_symbol_rejects_bad_polarity():
    with pytest.raises(ValueError, match="BJTSymbol.polarity"):
        BJTSymbol("Q1", x=0, y=0, polarity="N-channel")


def test_ground_symbol_emits_bare_point_and_type():
    p = Project()
    p.add(GroundSymbol("G1", x=2.5, y=3.5, type="TRIANGLE"))
    el = _parse(p).find("components/diylc.misc.GroundSymbol")
    pt = el.find("point")
    assert pt.attrib == {"x": "2.5", "y": "3.5"}
    assert el.find("type").text == "TRIANGLE"


def test_ground_symbol_rejects_bad_type():
    with pytest.raises(ValueError, match="GroundSymbol.type"):
        GroundSymbol("G1", x=0, y=0, type="EARTH")


def test_curved_trace_two_to_four_interpolation():
    p = Project()
    p.add(CurvedTrace("T1", points=[(0.0, 0.0), (3.0, 0.0)]))
    el = _parse(p).find("components/diylc.connectivity.CurvedTrace")
    cps = el.find("controlPoints2").findall("point")
    assert len(cps) == 4


def test_curved_trace_accepts_3_points():
    """Like HookupWire, CurvedTrace accepts any WIRE_POINT_COUNT count (≥2)."""
    CurvedTrace("T", points=[(0, 0), (1, 0), (2, 0)])  # 3 OK
    with pytest.raises(ValueError, match="at least 2 points"):
        CurvedTrace("T2", points=[(0, 0)])              # 1 fails


def test_all_new_symbols_round_trip(tmp_path):
    p = Project()
    p.add(ResistorSymbol("R", 1, 1, 1, 1.5, value="10K"))
    p.add(CapacitorSymbol("C", 2, 1, 2, 1.5, value="100nF"))
    p.add(DiodeSymbol("D", 3, 1, 3, 1.5))
    p.add(BJTSymbol("Q", x=4, y=1, polarity="NPN"))
    p.add(GroundSymbol("G", x=5, y=1))
    p.add(CurvedTrace("T", points=[(1, 2), (5, 2)]))

    out = tmp_path / "x.diy"
    p.save(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p2 = read_project(out)
    assert len(p2.components) == len(p.components)
    for c1, c2 in zip(p.components, p2.components):
        assert type(c1) is type(c2)


def test_dil__ic_alias_recognized(tmp_path):
    """Old DIYLC versions wrote `DIL__IC` (double underscore) for the same class."""
    xml = """<?xml version="1.0"?>
<project>
  <fileVersion><major>5</major><minor>0</minor><build>0</build></fileVersion>
  <title>x</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <diylc.semiconductors.DIL__IC>
      <name>U1</name>
      <pinCount>_8</pinCount>
      <controlPoints><point x="1.0" y="1.0"/></controlPoints>
    </diylc.semiconductors.DIL__IC>
  </components>
</project>
"""
    f = tmp_path / "x.diy"
    f.write_text(xml)
    p = read_project(f)
    from pydiylc import DIL_IC

    assert len(p.components) == 1
    assert isinstance(p.components[0], DIL_IC)
