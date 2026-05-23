"""Stress-test the reader/writer pipeline against the v3 XStream format.

These tests use small handcrafted fixtures that mirror the patterns found
in the upstream DIYLC regression corpus (we don't ship the corpus itself —
it's at github.com/bancika/diy-layout-creator). Each fixture exercises one
v3-specific quirk that real community files use.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from pydiylc import Project
from pydiylc.reader import read_project


def _write(tmp_path: Path, name: str, xml: str) -> Path:
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return p


def test_v3_full_round_trip_with_nested_measures(tmp_path):
    """A complete v3 file with nested-form Measures and references must
    read, re-emit, and re-read with the same component count + values."""
    xml = """<?xml version="1.0"?>
<org.diylc.core.Project>
  <title>v3 corpus-style</title>
  <author>test</author>
  <width value="10.0" unit="cm"/>
  <height value="6.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <org.diylc.components.connectivity.SolderPad>
      <name>P1</name>
      <size>
        <value>0.09</value>
        <unit>in</unit>
      </size>
      <color hex="000000"/>
      <point x="1.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize>
        <value>0.5</value>
        <unit>mm</unit>
      </holeSize>
    </org.diylc.components.connectivity.SolderPad>
    <org.diylc.components.connectivity.SolderPad>
      <name>P2</name>
      <size reference="../../org.diylc.components.connectivity.SolderPad/size"/>
      <color hex="000000"/>
      <point x="2.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize reference="../../org.diylc.components.connectivity.SolderPad/holeSize"/>
    </org.diylc.components.connectivity.SolderPad>
    <org.diylc.components.connectivity.SolderPad>
      <name>P3</name>
      <size reference="../../org.diylc.components.connectivity.SolderPad/size"/>
      <color hex="000000"/>
      <point x="3.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize reference="../../org.diylc.components.connectivity.SolderPad/holeSize"/>
    </org.diylc.components.connectivity.SolderPad>
  </components>
</org.diylc.core.Project>
"""
    f = _write(tmp_path, "v3.diy", xml)
    p = read_project(f)
    assert len(p.components) == 3
    # All three pads share the same size + holeSize.
    for pad in p.components:
        assert pad.size.value == 0.09
        assert pad.size.unit == "in"
        assert pad.hole_size.value == 0.5
        assert pad.hole_size.unit == "mm"

    # Re-emit and re-read.
    out = tmp_path / "rt.diy"
    p.save(out)
    p2 = read_project(out)
    assert len(p2.components) == 3
    for pad in p2.components:
        assert pad.size.value == 0.09
        assert pad.hole_size.value == 0.5


def test_v3_chained_references(tmp_path):
    """A reference can point at something that *also* has a reference. The
    resolver must do multiple passes (XStream emits them in any order)."""
    xml = """<?xml version="1.0"?>
<org.diylc.core.Project>
  <title>chained</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <org.diylc.components.connectivity.SolderPad>
      <name>P1</name>
      <size>
        <value>0.09</value>
        <unit>in</unit>
      </size>
      <color hex="000000"/>
      <point x="1.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize value="0.5" unit="mm"/>
    </org.diylc.components.connectivity.SolderPad>
    <org.diylc.components.connectivity.SolderPad>
      <name>P2</name>
      <size reference="../../org.diylc.components.connectivity.SolderPad/size"/>
      <color hex="000000"/>
      <point x="2.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize value="0.5" unit="mm"/>
    </org.diylc.components.connectivity.SolderPad>
    <org.diylc.components.connectivity.SolderPad>
      <name>P3</name>
      <size reference="../../org.diylc.components.connectivity.SolderPad[2]/size"/>
      <color hex="000000"/>
      <point x="3.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize value="0.5" unit="mm"/>
    </org.diylc.components.connectivity.SolderPad>
  </components>
</org.diylc.core.Project>
"""
    f = _write(tmp_path, "chained.diy", xml)
    p = read_project(f)
    assert len(p.components) == 3
    # P3's ref → P2's size → P1's size. All should be 0.09 in.
    for pad in p.components:
        assert pad.size.value == 0.09


def test_v3_unresolvable_reference_doesnt_crash(tmp_path):
    """A reference path that doesn't resolve (bad data) should be skipped
    with a warning, not crash the whole read."""
    xml = """<?xml version="1.0"?>
<org.diylc.core.Project>
  <title>bad ref</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <org.diylc.components.connectivity.SolderPad>
      <name>P1</name>
      <size reference="../../nonexistent/path"/>
      <color hex="000000"/>
      <point x="1.0" y="1.0"/>
      <type>ROUND</type>
      <holeSize value="0.5" unit="mm"/>
    </org.diylc.components.connectivity.SolderPad>
  </components>
</org.diylc.core.Project>
"""
    f = _write(tmp_path, "bad.diy", xml)
    # Shouldn't raise — the bad reference leaves the size as a default,
    # which the SolderPad's dataclass field has via default_factory.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = read_project(f)
    # We may end up with 0 or 1 components depending on whether the
    # constructor accepts the empty size; either is acceptable, but the
    # read should NOT raise.
    assert len(p.components) <= 1
