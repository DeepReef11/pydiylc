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


def test_tube_socket_b9a_has_center_plus_9_pins():
    # DIYLC stores the socket center as controlPoints[0] (the drag anchor
    # its updateControlPoints() rebuilds the ring from), then the pins.
    p = Project()
    p.add(TubeSocket("V1", x=3.0, y=3.0, base="B9A", tube_type="12AX7"))
    root = _parse(p)
    socket = root.find("components/diylc.tube.TubeSocket")
    assert socket.find("base").text == "B9A"
    assert socket.find("type").text == "12AX7"
    pts = socket.find("controlPoints").findall("point")
    assert len(pts) == 10
    assert (float(pts[0].get("x")), float(pts[0].get("y"))) == (3.0, 3.0)


def test_tube_socket_octal_has_center_plus_8_pins():
    p = Project()
    p.add(TubeSocket("V1", x=0, y=0, base="OCTAL"))
    pts = _parse(p).find(
        "components/diylc.tube.TubeSocket/controlPoints"
    ).findall("point")
    assert len(pts) == 9
    assert (float(pts[0].get("x")), float(pts[0].get("y"))) == (0.0, 0.0)


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


# ---------------------------------------------------------------------------
# Orientation must actually rotate derived pins (regression: 29 components
# accepted the enum, wrote it to the file, and ignored it in the geometry)
# ---------------------------------------------------------------------------


def test_orientation_rotates_pins_for_every_multipin_body():
    import dataclasses

    from pydiylc.components import ALL_COMPONENTS

    def base_kwargs(cls):
        kw = {}
        for f in dataclasses.fields(cls):
            if (
                f.default is not dataclasses.MISSING
                or f.default_factory is not dataclasses.MISSING
            ):
                continue
            if f.name == "name":
                kw["name"] = "X"
            elif f.name in ("x", "y"):
                kw[f.name] = 2.0
            elif f.name == "value":
                kw["value"] = "1"
            else:
                return None
        return kw

    ignored = []
    for cls in ALL_COMPONENTS:
        if not hasattr(cls, "_control_points"):
            continue
        kw = base_kwargs(cls)
        if kw is None:
            continue
        fields = {f.name for f in dataclasses.fields(cls)}
        if "orientation" not in fields:
            continue
        enums = (getattr(cls, "__enums__", None) or {}).get("orientation")
        if not enums or len(enums) < 2:
            continue
        layouts = {
            tuple(cls(**{**kw, "orientation": o})._control_points())
            for o in enums
        }
        pins = cls(**kw)._control_points()
        # A single pin sitting exactly on the anchor is rotation-invariant.
        if len(pins) == 1 and pins[0] == (2.0, 2.0):
            continue
        if len(layouts) == 1:
            ignored.append(cls.__name__)
    assert not ignored, f"orientation ignored by: {ignored}"


def test_oriented_rotation_matches_to92_convention():
    """_90 turns the DEFAULT layout clockwise about the anchor, exactly like
    the hand-rolled TransistorTO92 math."""
    from pydiylc import OpenJack1_4

    base = OpenJack1_4("J", x=2.0, y=2.0)._control_points()
    spun = OpenJack1_4("J", x=2.0, y=2.0, orientation="_90")._control_points()
    for (px, py), (qx, qy) in zip(base, spun):
        dx, dy = px - 2.0, py - 2.0
        assert (qx, qy) == (round(2.0 - dy, 3), round(2.0 + dx, 3))


def test_rotated_multipin_body_round_trips_cleanly(tmp_path):
    """Writer emits rotated pins with pin 0 on the anchor, so the reader
    recovers the same anchor + orientation for every value."""
    from pydiylc import OpenJack1_4

    for o in ("DEFAULT", "_90", "_180", "_270"):
        p = Project()
        p.add(OpenJack1_4("J1", x=2.0, y=2.0, orientation=o))
        f = tmp_path / "j.diy"
        p.save(f)
        j = Project.read(f).components[0]
        assert (j.x, j.y) == (2.0, 2.0)
        assert j.orientation == o
