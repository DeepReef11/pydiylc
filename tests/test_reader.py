"""Tests for the .diy file reader."""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pydiylc import (
    Project,
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    PotentiometerPanel,
    PerfBoard,
    VeroBoard,
    BlankBoard,
    SolderPad,
    CopperTrace,
    Jumper,
    HookupWire,
    Label,
    TransistorTO92,
    DIL_IC,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
    TraceCut,
    DiodePlastic,
    LED,
    RadialCeramicDiskCapacitor,
    Dot,
    Eyelet,
    Turret,
    Line,
)
from pydiylc.reader import read_project, read_warnings, _camel_to_snake, _TAG_TO_CLASS


def test_camel_to_snake_handles_common_cases():
    assert _camel_to_snake("bodyColor") == "body_color"
    assert _camel_to_snake("name") == "name"
    assert _camel_to_snake("DCPolarity") == "dc_polarity"
    assert _camel_to_snake("showLabels") == "show_labels"


def test_tag_to_class_includes_both_short_and_long_prefixes():
    # Modern short form
    assert "diylc.passive.Resistor" in _TAG_TO_CLASS
    # Older v3-style fully qualified form
    assert "org.diylc.components.passive.Resistor" in _TAG_TO_CLASS
    # Should resolve to the same class
    assert _TAG_TO_CLASS["diylc.passive.Resistor"] is _TAG_TO_CLASS["org.diylc.components.passive.Resistor"]


def test_read_minimal_project(tmp_path):
    p = Project(title="basic", width_cm=10, height_cm=8)
    p.add(Resistor("R1", 1.0, 1.0, 1.0, 1.5, value="10K"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.title == "basic"
    assert abs(p2.width_cm - 10) < 0.01
    assert len(p2.components) == 1
    r = p2.components[0]
    assert isinstance(r, Resistor)
    assert r.name == "R1"
    assert r.value == "10K"


def test_resistor_value_round_trips_as_string(tmp_path):
    p = Project()
    p.add(Resistor("R1", 0, 0, 0, 0.5, value="4.7K"))
    p.add(Resistor("R2", 0, 1, 0, 1.5, value="1M"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.components[0].value == "4.7K"
    assert p2.components[1].value == "1M"


def test_capacitor_value_round_trips(tmp_path):
    p = Project()
    p.add(RadialFilmCapacitor("C1", 0, 0, 0, 0.1, value="100nF"))
    p.add(RadialElectrolytic("C2", 0, 1, 0, 1.1, value="22uF"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    assert p2.components[0].value == "100nF"
    assert p2.components[1].value == "22uF"


def test_pot_resistance_round_trips(tmp_path):
    p = Project()
    p.add(PotentiometerPanel("VR1", x=1, y=1, resistance="100K", taper="LOG"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    pot = p2.components[0]
    assert pot.resistance == "100K"
    assert pot.taper == "LOG"


def test_solder_pad_uses_bare_point_element(tmp_path):
    p = Project()
    p.add(SolderPad("Pad1", x=1.5, y=2.5))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    pad = p2.components[0]
    assert pad.x == 1.5 and pad.y == 2.5


def test_label_position_and_text(tmp_path):
    p = Project()
    p.add(Label("L1", x=1.2, y=3.4, text="hello"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    lbl = p2.components[0]
    assert lbl.text == "hello"
    assert lbl.x == 1.2 and lbl.y == 3.4


def test_two_pin_drops_midpoint(tmp_path):
    """Two-pin components emit [p1, p2, mid] but read back the first two."""
    p = Project()
    p.add(Resistor("R1", 1.0, 2.0, 5.0, 2.0, value="10K"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    r = p2.components[0]
    assert (r.x1, r.y1) == (1.0, 2.0)
    assert (r.x2, r.y2) == (5.0, 2.0)


def test_hookup_wire_keeps_four_points(tmp_path):
    p = Project()
    p.add(HookupWire("W1", points=[(0, 0), (1, 0), (2, 0), (3, 0)], color="ff0000"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    w = p2.components[0]
    assert len(w.points) == 4
    assert w.color == "ff0000"


def test_transistor_anchor_preserved(tmp_path):
    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=1.5, value="2N5088"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    q = p2.components[0]
    assert (q.x, q.y) == (2.0, 1.5)
    assert q.value == "2N5088"


def test_dil_anchor_and_pin_count(tmp_path):
    p = Project()
    p.add(DIL_IC("U1", x=3.0, y=2.0, value="TL072", pin_count="_8"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    u = p2.components[0]
    assert u.pin_count == "_8"
    assert u.value == "TL072"


def test_mini_toggle_switch_type(tmp_path):
    p = Project()
    p.add(MiniToggleSwitch("SW1", x=2, y=2, switch_type="_3PDT"))
    out = tmp_path / "x.diy"
    p.save(out)
    p2 = read_project(out)
    sw = p2.components[0]
    assert sw.switch_type == "_3PDT"


def test_full_corpus_components_round_trip(tmp_path):
    """One Project containing every component type."""
    p = Project(title="all", width_cm=20, height_cm=15)
    p.add(BlankBoard("BB", 0, 0, 1, 1))
    p.add(PerfBoard("PB", 0, 1, 1, 2))
    p.add(VeroBoard("VB", 0, 2, 1, 3))
    p.add(Resistor("R", 0, 3, 0, 3.5, value="10K"))
    p.add(RadialFilmCapacitor("Cf", 0.5, 3, 0.5, 3.5, value="100nF"))
    p.add(RadialCeramicDiskCapacitor("Cc", 1, 3, 1, 3.5, value="100pF"))
    p.add(RadialElectrolytic("Ce", 1.5, 3, 1.5, 3.5, value="22uF"))
    p.add(PotentiometerPanel("VR", x=2, y=3, resistance="100K"))
    p.add(DiodePlastic("D", 2.5, 3, 2.5, 3.5))
    p.add(LED("LED", 3, 3, 3, 3.5))
    p.add(TransistorTO92("Q", x=3.5, y=3))
    p.add(DIL_IC("U", x=4, y=3, pin_count="_8"))
    p.add(CopperTrace("T", points=[(0, 4), (1, 4)]))
    p.add(Jumper("J", 0, 4.2, 1, 4.2))
    p.add(HookupWire("W", points=[(0, 4.4), (1, 4.4)]))
    p.add(SolderPad("Pad", x=0.5, y=4.6))
    p.add(Dot("Dot", x=0.7, y=4.6))
    p.add(Eyelet("Eye", x=0.9, y=4.6))
    p.add(Turret("Tur", x=1.1, y=4.6))
    p.add(Line("Ln", points=[(0, 5), (1, 5)]))
    p.add(TraceCut("TC", x=0.5, y=4.8))
    p.add(MiniToggleSwitch("SW", x=2, y=5, switch_type="DPDT"))
    p.add(PlasticDCJack("DC", x=3, y=5))
    p.add(OpenJack1_4("AJ", x=4, y=5))
    p.add(Label("L", x=0, y=6, text="x"))

    out = tmp_path / "all.diy"
    p.save(out)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p2 = read_project(out)

    assert read_warnings(p2) == []
    assert len(p2.components) == len(p.components)
    for c1, c2 in zip(p.components, p2.components):
        assert type(c1) is type(c2), f"{type(c1).__name__} vs {type(c2).__name__}"
        assert c1.name == c2.name


def test_unknown_component_does_not_break_parse(tmp_path):
    """An unrecognized component type produces a warning, not an exception."""
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
<project>
  <fileVersion><major>5</major><minor>0</minor><build>0</build></fileVersion>
  <title>x</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <diylc.tube.TubeSocket>
      <name>V1</name>
    </diylc.tube.TubeSocket>
    <diylc.connectivity.SolderPad>
      <name>P1</name>
      <size value="3.0" unit="mm"/>
      <color hex="000000"/>
      <point x="1.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize value="0.8" unit="mm"/>
    </diylc.connectivity.SolderPad>
  </components>
</project>
"""
    f = tmp_path / "x.diy"
    f.write_text(xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    # Should have skipped the tube socket but kept the solder pad
    assert len(p.components) == 1
    assert isinstance(p.components[0], SolderPad)
    warnings_ = read_warnings(p)
    assert any("TubeSocket" in w for w in warnings_)


def test_wrong_root_raises(tmp_path):
    f = tmp_path / "x.diy"
    f.write_text('<?xml version="1.0"?><weird/>')
    with pytest.raises(ValueError, match="expected <project>"):
        read_project(f)


def test_v3_long_form_root_accepted(tmp_path):
    """Older XStream-serialized files use <org.diylc.core.Project>."""
    xml = """<?xml version="1.0"?>
<org.diylc.core.Project>
  <title>v3</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components/>
</org.diylc.core.Project>
"""
    f = tmp_path / "x.diy"
    f.write_text(xml)
    p = read_project(f)
    assert p.title == "v3"


def test_v3_long_form_components_recognized(tmp_path):
    """v3 files use the org.diylc.components.* prefix."""
    xml = """<?xml version="1.0"?>
<org.diylc.core.Project>
  <title>v3</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <org.diylc.components.connectivity.SolderPad>
      <name>P1</name>
      <size value="3.0" unit="mm"/>
      <color hex="000000"/>
      <point x="1.5" y="2.5"/>
      <type>ROUND</type>
      <holeSize value="0.8" unit="mm"/>
    </org.diylc.components.connectivity.SolderPad>
  </components>
</org.diylc.core.Project>
"""
    f = tmp_path / "x.diy"
    f.write_text(xml)
    p = read_project(f)
    assert len(p.components) == 1
    assert isinstance(p.components[0], SolderPad)


def test_project_read_classmethod(tmp_path):
    """Project.read(path) is a thin wrapper."""
    p = Project(title="cm")
    p.save(tmp_path / "x.diy")
    p2 = Project.read(tmp_path / "x.diy")
    assert p2.title == "cm"
