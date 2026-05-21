"""Tests for the components added this round: TubeSocket, Axial caps, shapes."""

from __future__ import annotations

import tempfile
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pydiylc import (
    Project,
    TubeSocket,
    AxialFilmCapacitor,
    AxialElectrolyticCapacitor,
    Rectangle,
    Ellipse,
)
from pydiylc.reader import read_project


def _parse(p: Project) -> ET.Element:
    return ET.fromstring(p.to_xml())


def test_tube_socket_b9a_has_9_pins():
    p = Project()
    p.add(TubeSocket("V1", x=3.0, y=3.0, base="B9A", tube_type="12AX7"))
    root = _parse(p)
    socket = root.find("components/diylc.tube.TubeSocket")
    assert socket.find("base").text == "B9A"
    assert socket.find("type").text == "12AX7"
    pts = socket.find("controlPoints").findall("point")
    assert len(pts) == 9


def test_tube_socket_octal_has_8_pins():
    p = Project()
    p.add(TubeSocket("V1", x=0, y=0, base="OCTAL"))
    pts = _parse(p).find(
        "components/diylc.tube.TubeSocket/controlPoints"
    ).findall("point")
    assert len(pts) == 8


def test_tube_socket_rejects_bad_base():
    with pytest.raises(ValueError, match="TubeSocket.base"):
        TubeSocket("V1", x=0, y=0, base="NOVAL")


def test_tube_socket_rejects_bad_mount():
    with pytest.raises(ValueError, match="TubeSocket.mount"):
        TubeSocket("V1", x=0, y=0, mount="WALL")


def test_axial_film_value_parses_as_string():
    p = Project()
    p.add(AxialFilmCapacitor("C1", 1.0, 5.0, 2.0, 5.0, value="22nF"))
    root = _parse(p)
    c = root.find("components/diylc.passive.AxialFilmCapacitor")
    val = c.find("value")
    assert val.attrib == {"value": "22.0", "unit": "nF"}


def test_axial_electro_polarized_by_default():
    p = Project()
    p.add(AxialElectrolyticCapacitor("C1", 1.0, 5.0, 2.0, 5.0, value="22uF"))
    root = _parse(p)
    c = root.find("components/diylc.passive.AxialElectrolyticCapacitor")
    assert c.find("polarized").text == "true"
    assert c.find("value").attrib == {"value": "22.0", "unit": "uF"}


def test_rectangle_corners_and_border():
    p = Project()
    p.add(Rectangle("box", 1.0, 2.0, 5.0, 4.0, border_color="ff0000"))
    root = _parse(p)
    r = root.find("components/diylc.shapes.Rectangle")
    cps = r.find("controlPoints").findall("point")
    assert cps[0].attrib == {"x": "1.0", "y": "2.0"}
    assert cps[1].attrib == {"x": "5.0", "y": "4.0"}
    assert r.find("borderColor").attrib == {"hex": "ff0000"}


def test_ellipse_emits_corners():
    p = Project()
    p.add(Ellipse("oval", 1.0, 1.0, 3.0, 2.0))
    root = _parse(p)
    e = root.find("components/diylc.shapes.Ellipse")
    cps = e.find("controlPoints").findall("point")
    assert cps[0].attrib == {"x": "1.0", "y": "1.0"}
    assert cps[1].attrib == {"x": "3.0", "y": "2.0"}


def test_new_components_round_trip(tmp_path):
    """All new components should round-trip through .diy without warnings."""
    p = Project(title="new")
    p.add(TubeSocket("V1", x=3.0, y=3.0, base="B9A", tube_type="12AX7"))
    p.add(TubeSocket("V2", x=5.0, y=3.0, base="OCTAL", tube_type="6L6"))
    p.add(AxialFilmCapacitor("C1", 1.0, 5.0, 2.0, 5.0, value="22nF"))
    p.add(AxialElectrolyticCapacitor("C2", 1.0, 6.0, 2.0, 6.0, value="22uF"))
    p.add(Rectangle("box1", 0.5, 0.5, 5.0, 5.0, border_color="0000ff"))
    p.add(Ellipse("oval1", 6.0, 6.0, 8.0, 7.0))

    out = tmp_path / "x.diy"
    p.save(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p2 = read_project(out)

    assert len(p2.components) == len(p.components)
    for c1, c2 in zip(p.components, p2.components):
        assert type(c1) is type(c2)
        assert c1.name == c2.name

    v1 = next(c for c in p2.components if c.name == "V1")
    assert v1.tube_type == "12AX7"
    assert v1.base == "B9A"

    c1 = next(c for c in p2.components if c.name == "C1")
    assert c1.value == "22nF"
