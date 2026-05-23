"""Tests for the v1 DIYLC reader (legacy <Layout>-root format).

v1 files use a flat, attribute-only schema with integer perfboard-hole
coordinates. The reader synthesizes an implicit board and converts each
element to its modern pydiylc equivalent.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from pydiylc import Project, PerfBoard, VeroBoard, Resistor, SolderPad, Label
from pydiylc.components import (
    AxialElectrolyticCapacitor, CopperTrace, DiodePlastic, HookupWire,
    LED, OpenJack1_4, PotentiometerPanel, RadialFilmCapacitor, TraceCut,
    TransistorTO92, _split_value,
)
from pydiylc.reader import read_project


def _write(tmp_path: Path, name: str, xml: str) -> Path:
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tolerant value parsing — drives the round-trip stability for messy v1 files.
# ---------------------------------------------------------------------------

def test_split_value_decimal_comma():
    """European decimal: '3,3K' must parse as 3.3, not crash."""
    assert _split_value("3,3K", "K") == (3.3, "K")


def test_split_value_suffix_decimal_point():
    """'2k2' is electronics-shorthand for 2.2k — used widely in EU schematics."""
    assert _split_value("2k2", "K") == (2.2, "k")
    assert _split_value("4M7", "K") == (4.7, "M")


def test_split_value_combined_label():
    """Some v1 files cram multiple specs into Value, e.g. '25 V 2500uF'.

    The capacitance is the meaningful number; pick the last numeric token.
    """
    n, u = _split_value("25 V 2500uF", "uF")
    assert n == 2500.0
    assert u == "uF"


def test_split_value_free_text_doesnt_crash():
    """A label like 'ceramic' has no number — fall back to 0+default, don't raise."""
    assert _split_value("ceramic", "pF") == (0.0, "pF")


def test_split_value_trailing_marker():
    """'1M*' (* often means non-polarized or matched). Drop the marker."""
    n, u = _split_value("1M*", "K")
    assert n == 1.0
    assert u == "M"


# ---------------------------------------------------------------------------
# v1 reader.
# ---------------------------------------------------------------------------

def test_v1_perfboard_layout(tmp_path):
    """A complete v1 perfboard with one resistor + pads + a wire."""
    xml = """<Layout Width="20" Height="10" Type="Perfboard" Project="Test">
    <Resistor Value="10K" X1="5" Y1="3" X2="5" Y2="6" Name="R1"/>
    <Pad Color="Black" X1="5" Y1="3" Name="P1"/>
    <Pad Color="Black" X1="5" Y1="6" Name="P2"/>
    <Wire Color="Black" Seed="123" X1="5" Y1="6" X2="10" Y2="6" Name="W1"/>
    <Text Value="Test label" X1="2" Y1="2" Name="L1"/>
</Layout>"""
    f = _write(tmp_path, "v1.diy", xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    assert p.title == "Test"
    # Implicit board + 5 explicit elements (Text included).
    by_type = {type(c).__name__ for c in p.components}
    assert "PerfBoard" in by_type
    assert "Resistor" in by_type
    assert "SolderPad" in by_type
    assert "HookupWire" in by_type
    assert "Label" in by_type
    # v1 coords are hole indices (0.1 in/hole) + a 2-hole inset.
    # X1=5 should become x=(5+2)*0.1 = 0.7 inches.
    r = next(c for c in p.components if isinstance(c, Resistor))
    assert r.x1 == pytest.approx(0.7)
    assert r.y1 == pytest.approx(0.5)


def test_v1_stripboard_layout(tmp_path):
    """Layout Type='Stripboard' synthesizes a VeroBoard."""
    xml = """<Layout Width="15" Height="8" Type="Stripboard" Project="Strip">
    <Cut X1="3" Y1="4" Name="C1"/>
</Layout>"""
    f = _write(tmp_path, "strip.diy", xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    assert any(isinstance(c, VeroBoard) for c in p.components)
    assert any(isinstance(c, TraceCut) for c in p.components)


def test_v1_pot_taper_mapping(tmp_path):
    """v1 'Audio' / 'Linear' / 'Reverse Audio' map to LOG/LIN/REV_LOG."""
    xml = """<Layout Width="10" Height="5" Type="Perfboard" Project="Pots">
    <Pot Value="100K" Taper="Audio"        X1="2" Y1="2" X2="4" Y2="2" Name="P_audio"/>
    <Pot Value="10K"  Taper="Linear"       X1="6" Y1="2" X2="8" Y2="2" Name="P_lin"/>
    <Pot Value="50K"  Taper="Reverse Audio" X1="2" Y1="4" X2="4" Y2="4" Name="P_rev"/>
</Layout>"""
    f = _write(tmp_path, "pots.diy", xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    pots = {c.name: c for c in p.components if isinstance(c, PotentiometerPanel)}
    assert pots["P_audio"].taper == "LOG"
    assert pots["P_lin"].taper == "LIN"
    assert pots["P_rev"].taper == "REV_LOG"


def test_v1_unknown_element_warns_not_raises(tmp_path):
    """A novel element type should record a warning and skip — not crash."""
    xml = """<Layout Width="10" Height="5" Type="Perfboard" Project="X">
    <FuturisticGadget X1="1" Y1="1" Name="G1"/>
    <Resistor Value="1K" X1="2" Y1="2" X2="2" Y2="4" Name="R1"/>
</Layout>"""
    f = _write(tmp_path, "novel.diy", xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    assert any(isinstance(c, Resistor) for c in p.components)
    assert any("unknown v1 element" in w for w in p._read_warnings)


def test_v1_roundtrip_handles_messy_values(tmp_path):
    """v1 files with non-canonical Value strings must read AND re-emit cleanly."""
    xml = """<Layout Width="10" Height="5" Type="Perfboard" Project="Messy">
    <Resistor Value="2k2"        X1="2" Y1="2" X2="2" Y2="4" Name="R1"/>
    <Capacitor Value="3,3uF"     X1="4" Y1="2" X2="4" Y2="4" Name="C1"/>
    <Electrolyte Value="25 V 2500uF" Size="Large" X1="6" Y1="2" X2="6" Y2="4" Name="C2"/>
</Layout>"""
    f = _write(tmp_path, "messy.diy", xml)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
        out = tmp_path / "messy_rt.diy"
        p.save(out)  # must not raise even though value strings are unusual
        p2 = read_project(out)
    # Component count survives the round-trip (1 board + 3 components).
    assert sum(1 for c in p2.components
               if type(c).__name__ in ("Resistor", "RadialFilmCapacitor",
                                       "AxialElectrolyticCapacitor")) == 3
