"""DIYLC component emitters.

Every component class:
- Has `__diylc_class__` set to the exact XML element it emits.
- Lists enum-valued fields in `__enums__` (field -> tuple of allowed values).
- Validates enums in `__post_init__` with helpful errors.
- Has a docstring with a one-line purpose, the XML element, and an example.

This metadata is what makes pydiylc AI-friendly: see `pydiylc.catalog` for
machine-readable schema, and `LLMS.txt` for the assistant-facing doc.

Coordinates are floats in DIYLC's project units (default inches; the
project's grid is 0.1 in). Two-pin components accept `x1,y1,x2,y2` and
emit a `[p1, p2, midpoint]` triplet, which is how DIYLC writes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Sequence

from .core import Measure, fmt, hex_color, esc, inches, mm
from . import enums as E


Point = tuple[float, float]


def _indent(n: int) -> str:
    return " " * n


def _points_block(tag: str, pts: Sequence[Point], indent: int) -> str:
    pad = _indent(indent)
    inner = _indent(indent + 2)
    lines = [f"{pad}<{tag}>"]
    for x, y in pts:
        lines.append(f'{inner}<point x="{fmt(x)}" y="{fmt(y)}"/>')
    lines.append(f"{pad}</{tag}>")
    return "\n".join(lines)


def _two_point_with_mid(p1: Point, p2: Point) -> list[Point]:
    """DIYLC two-pin components store [p1, p2, midpoint] as <points>."""
    mx = (p1[0] + p2[0]) / 2.0
    my = (p1[1] + p2[1]) / 2.0
    return [p1, p2, (mx, my)]


@dataclass
class Component:
    """Base class. Subclasses set `__diylc_class__` and emit XML via `to_xml`."""

    __diylc_class__: ClassVar[str] = ""
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {}

    def to_xml(self, indent: int = 4) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def _validate_enums(self) -> None:
        for field_name, allowed in self.__enums__.items():
            E.check(f"{type(self).__name__}.{field_name}", getattr(self, field_name), allowed)


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@dataclass
class BlankBoard(Component):
    """Blank rectangular board.

    XML: ``<diylc.boards.BlankBoard>``

    Example::

        p.add(BlankBoard("Board1", x1=1.0, y1=1.0, x2=2.0, y2=1.7))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    alpha: int = 0
    value: str = ""
    board_color: str = "ccffff"
    border_color: str = "66ccff"
    type: str = "SQUARE"

    __diylc_class__: ClassVar[str] = "diylc.boards.BlankBoard"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {"type": E.BOARD_TYPE}

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.boards.BlankBoard>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}    <point x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f'{pad}  <firstPoint x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}  <secondPoint x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f'{pad}  <boardColor hex="{hex_color(self.board_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}  <mode>TwoPoints</mode>\n"
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}</diylc.boards.BlankBoard>"
        )


@dataclass
class PerfBoard(Component):
    """Perfboard with through-hole pads on a grid.

    XML: ``<diylc.boards.PerfBoard>``

    Example::

        p.add(PerfBoard("Board1", x1=1.0, y1=1.0, x2=3.0, y2=2.5))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    alpha: int = 62
    value: str = ""
    board_color: str = "f8ebb3"
    border_color: str = "ada47d"
    pad_color: str = "da8a67"
    coordinate_color: str = "b6b6b6"
    spacing: Measure = field(default_factory=lambda: inches(0.1))
    x_type: str = "Numbers"
    y_type: str = "Letters"
    coordinate_origin: str = "Top_Left"
    coordinate_display: str = "One_Side"

    __diylc_class__: ClassVar[str] = "diylc.boards.PerfBoard"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "x_type": E.COORDINATE_AXIS,
        "y_type": E.COORDINATE_AXIS,
        "coordinate_origin": E.COORDINATE_ORIGIN,
        "coordinate_display": E.COORDINATE_DISPLAY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.boards.PerfBoard>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}    <point x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f'{pad}  <firstPoint x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}  <secondPoint x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f'{pad}  <boardColor hex="{hex_color(self.board_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <coordinateColor hex="{hex_color(self.coordinate_color)}"/>\n'
            f"{pad}  <xType>{self.x_type}</xType>\n"
            f"{pad}  <coordinateOrigin>{self.coordinate_origin}</coordinateOrigin>\n"
            f"{pad}  <coordinateDisplay>{self.coordinate_display}</coordinateDisplay>\n"
            f"{pad}  <yType>{self.y_type}</yType>\n"
            f"{pad}  <mode>TwoPoints</mode>\n"
            f"{pad}  <spacing {self.spacing.attrs()}/>\n"
            f'{pad}  <padColor hex="{hex_color(self.pad_color)}"/>\n'
            f"{pad}</diylc.boards.PerfBoard>"
        )


# ---------------------------------------------------------------------------
# Passives
# ---------------------------------------------------------------------------


@dataclass
class Resistor(Component):
    """Through-hole resistor between two points.

    XML: ``<diylc.passive.Resistor>``

    `value` accepts strings like ``"4.7K"``, ``"1M"``, ``"470R"``. Bare numbers
    default to ``"K"``.

    Example::

        p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5, value="10K"))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "1K"
    power: str = "HALF"
    color_code: str = "_5_BAND"
    shape: str = "Standard"
    alpha: int = 127
    body_color: str = "82cffd"
    border_color: str = "5b90b1"
    label_color: str = "000000"
    lead_color: str = "636363"
    length: Measure = field(default_factory=lambda: inches(0.5))
    width: Measure = field(default_factory=lambda: inches(0.125))
    display: str = "VALUE"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.Resistor"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "power": E.POWER,
        "color_code": E.RESISTOR_COLOR_CODE,
        "shape": E.RESISTOR_SHAPE,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="K")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.Resistor>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <power>{self.power}</power>\n"
            f"{pad}  <colorCode>{self.color_code}</colorCode>\n"
            f"{pad}  <shape>{self.shape}</shape>\n"
            f"{pad}</diylc.passive.Resistor>"
        )


def _split_value(s: str, default_unit: str) -> tuple[float, str]:
    """Parse strings like "4.7K", "470nF", "22uF" into (value, unit)."""
    import re

    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]+)?\s*$", s)
    if not m:
        raise ValueError(f"can't parse value: {s!r}")
    num = float(m.group(1))
    unit = m.group(2) or default_unit
    return num, unit


@dataclass
class RadialFilmCapacitor(Component):
    """Radial-lead film capacitor (e.g. polyester box).

    XML: ``<diylc.passive.RadialFilmCapacitor>``

    `value` accepts ``"100nF"``, ``"470n"``, ``"1uF"``. Bare numbers default
    to ``"nF"``.

    Example::

        p.add(RadialFilmCapacitor("C1", x1=1.0, y1=1.0, x2=1.0, y2=1.1,
                                   value="100nF", voltage="_63V"))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "100nF"
    voltage: str = "_63V"
    alpha: int = 127
    body_color: str = "ffe303"
    border_color: str = "b29e02"
    label_color: str = "000000"
    lead_color: str = "636363"
    length: Measure = field(default_factory=lambda: mm(7.5))
    width: Measure = field(default_factory=lambda: mm(6.0))
    pin_spacing: Measure = field(default_factory=lambda: inches(0.1))
    display: str = "VALUE"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    show_outer_foil: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.RadialFilmCapacitor"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "voltage": E.VOLTAGE,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="nF")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.RadialFilmCapacitor>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <voltage>{self.voltage}</voltage>\n"
            f"{pad}  <showOuterFoil>{str(self.show_outer_foil).lower()}</showOuterFoil>\n"
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f"{pad}</diylc.passive.RadialFilmCapacitor>"
        )


@dataclass
class RadialCeramicDiskCapacitor(Component):
    """Ceramic disk capacitor.

    XML: ``<diylc.passive.RadialCeramicDiskCapacitor>``

    `value` accepts ``"100pF"``, ``"1000pF"``, ``".01uF"``. Bare numbers
    default to ``"pF"``.
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "100pF"
    voltage: str = "_63V"
    alpha: int = 127
    body_color: str = "f0e68c"
    border_color: str = "a8a162"
    label_color: str = "000000"
    lead_color: str = "636363"
    length: Measure = field(default_factory=lambda: inches(0.4))
    width: Measure = field(default_factory=lambda: inches(0.125))
    pin_spacing: Measure = field(default_factory=lambda: inches(0.1))
    display: str = "VALUE"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.RadialCeramicDiskCapacitor"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "voltage": E.VOLTAGE,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="pF")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.RadialCeramicDiskCapacitor>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <voltage>{self.voltage}</voltage>\n"
            f"{pad}</diylc.passive.RadialCeramicDiskCapacitor>"
        )


@dataclass
class RadialElectrolytic(Component):
    """Polarized radial electrolytic capacitor.

    XML: ``<diylc.passive.RadialElectrolytic>``

    `value` accepts ``"22uF"``, ``"470uF"``. Bare numbers default to ``"uF"``.
    First point is the positive lead unless ``invert=True``.

    Example::

        p.add(RadialElectrolytic("C1", 1.0, 1.0, 1.0, 1.1, value="22uF", voltage="_25V"))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "10uF"
    voltage: str = "_25V"
    alpha: int = 127
    body_color: str = "eaadea"
    border_color: str = "a379a3"
    label_color: str = "000000"
    lead_color: str = "636363"
    length: Measure = field(default_factory=lambda: mm(16.0))
    pin_spacing: Measure = field(default_factory=lambda: inches(0.1))
    height: Measure = field(default_factory=lambda: inches(0.4))
    display: str = "VALUE"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    marker_color: str = "808080"
    tick_color: str = "ffffff"
    polarized: bool = True
    folded: bool = False
    invert: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.RadialElectrolytic"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "voltage": E.VOLTAGE,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="uF")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.RadialElectrolytic>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <voltage>{self.voltage}</voltage>\n"
            f'{pad}  <markerColor hex="{hex_color(self.marker_color)}"/>\n'
            f'{pad}  <tickColor hex="{hex_color(self.tick_color)}"/>\n'
            f"{pad}  <polarized>{str(self.polarized).lower()}</polarized>\n"
            f"{pad}  <folded>{str(self.folded).lower()}</folded>\n"
            f"{pad}  <height {self.height.attrs()}/>\n"
            f"{pad}  <invert>{str(self.invert).lower()}</invert>\n"
            f"{pad}</diylc.passive.RadialElectrolytic>"
        )


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


@dataclass
class CopperTrace(Component):
    """Straight or polyline copper trace.

    XML: ``<diylc.connectivity.CopperTrace>``

    Pass at least two points. Two-point traces get a midpoint added,
    matching how DIYLC stores them.

    Example::

        p.add(CopperTrace("T1", points=[(1.0, 1.0), (2.0, 1.0)]))
    """

    name: str
    points: Sequence[Point]
    thickness: Measure = field(default_factory=lambda: mm(2.0))
    alpha: int = 127
    body_color: str = "ffffff"
    border_color: str = "000000"
    label_color: str = "000000"
    lead_color: str = "000000"
    display: str = "NAME"
    flip_standing: bool = False
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.connectivity.CopperTrace"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {"display": E.DISPLAY}

    def __post_init__(self) -> None:
        self._validate_enums()
        if len(self.points) < 2:
            raise ValueError("CopperTrace requires at least 2 points")

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = list(self.points)
        if len(pts) == 2:
            mx = (pts[0][0] + pts[1][0]) / 2.0
            my = (pts[0][1] + pts[1][1]) / 2.0
            pts = [pts[0], pts[1], (mx, my)]
        return (
            f"{pad}<diylc.connectivity.CopperTrace>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <thickness {self.thickness.attrs()}/>\n"
            f"{pad}</diylc.connectivity.CopperTrace>"
        )


@dataclass
class Jumper(Component):
    """Insulated jumper wire between two pads.

    XML: ``<diylc.connectivity.Jumper>``
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = "0000ff"
    style: str = "SOLID"
    alpha: int = 127
    body_color: str = "ffffff"
    border_color: str = "000000"
    label_color: str = "000000"
    lead_color: str = "0000ff"
    display: str = "NAME"
    flip_standing: bool = False
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.connectivity.Jumper"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "style": E.LINE_STYLE,
        "display": E.DISPLAY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.connectivity.Jumper>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <style>{self.style}</style>\n"
            f"{pad}</diylc.connectivity.Jumper>"
        )


@dataclass
class HookupWire(Component):
    """Curved insulated hookup wire with 4 control points.

    XML: ``<diylc.connectivity.HookupWire>``

    Pass 2 endpoints (interpolated to 4) or 4 control points directly.
    """

    name: str
    points: Sequence[Point]
    color: str = "000000"
    gauge: str = "_22"
    style: str = "SOLID"
    striped: bool = False
    smooth: bool = True
    alpha: int = 127
    point_count: str = "FOUR"

    __diylc_class__: ClassVar[str] = "diylc.connectivity.HookupWire"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "gauge": E.WIRE_GAUGE,
        "style": E.LINE_STYLE,
        "point_count": E.WIRE_POINT_COUNT,
    }

    def __post_init__(self) -> None:
        self._validate_enums()
        if len(self.points) not in (2, 4):
            raise ValueError("HookupWire needs 2 or 4 points")

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = list(self.points)
        if len(pts) == 2:
            (x1, y1), (x2, y2) = pts
            pts = [
                (x1, y1),
                (x1 + (x2 - x1) / 3.0, y1 + (y2 - y1) / 3.0),
                (x1 + 2 * (x2 - x1) / 3.0, y1 + 2 * (y2 - y1) / 3.0),
                (x2, y2),
            ]
        return (
            f"{pad}<diylc.connectivity.HookupWire>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints2', pts, indent + 2)}\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <pointCount>{self.point_count}</pointCount>\n"
            f"{pad}  <style>{self.style}</style>\n"
            f"{pad}  <smooth>{str(self.smooth).lower()}</smooth>\n"
            f"{pad}  <lastUpdatePointIndex>-1</lastUpdatePointIndex>\n"
            f"{pad}  <gauge>{self.gauge}</gauge>\n"
            f"{pad}  <striped>{str(self.striped).lower()}</striped>\n"
            f"{pad}</diylc.connectivity.HookupWire>"
        )


@dataclass
class SolderPad(Component):
    """Single solder pad / drilled hole.

    XML: ``<diylc.connectivity.SolderPad>``
    """

    name: str
    x: float
    y: float
    size: Measure = field(default_factory=lambda: mm(3.0))
    color: str = "000000"
    type: str = "ROUND"
    hole_size: Measure = field(default_factory=lambda: mm(0.8))

    __diylc_class__: ClassVar[str] = "diylc.connectivity.SolderPad"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {"type": E.PAD_TYPE}

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.connectivity.SolderPad>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}  <holeSize {self.hole_size.attrs()}/>\n"
            f"{pad}</diylc.connectivity.SolderPad>"
        )


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


@dataclass
class Label(Component):
    """Free-floating text label.

    XML: ``<diylc.misc.Label>``

    `font_style`: 0=plain, 1=bold, 2=italic, 3=bold+italic.
    """

    name: str
    x: float
    y: float
    text: str
    font: str = "Tahoma"
    font_size: int = 14
    font_style: int = 0
    color: str = "000000"
    center: bool = True
    horizontal_alignment: str = "CENTER"
    vertical_alignment: str = "CENTER"
    orientation: str = "DEFAULT"

    __diylc_class__: ClassVar[str] = "diylc.misc.Label"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "horizontal_alignment": E.HORIZONTAL_ALIGNMENT,
        "vertical_alignment": E.VERTICAL_ALIGNMENT,
        "orientation": E.LABEL_ORIENTATION_4,
    }

    def __post_init__(self) -> None:
        self._validate_enums()
        if self.font_style not in (0, 1, 2, 3):
            raise ValueError(
                f"Label.font_style: expected 0..3 (0=plain,1=bold,2=italic,3=bold+italic), got {self.font_style!r}"
            )

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.misc.Label>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  <text>{esc(self.text)}</text>\n"
            f'{pad}  <font name="{esc(self.font)}" size="{self.font_size}" style="{self.font_style}"/>\n'
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <center>{str(self.center).lower()}</center>\n"
            f"{pad}  <horizontalAlignment>{self.horizontal_alignment}</horizontalAlignment>\n"
            f"{pad}  <verticalAlignment>{self.vertical_alignment}</verticalAlignment>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}</diylc.misc.Label>"
        )


# Public registry of every Component subclass — used by `pydiylc.catalog`
# to build the machine-readable schema.
ALL_COMPONENTS: tuple[type[Component], ...] = (
    BlankBoard,
    PerfBoard,
    Resistor,
    RadialFilmCapacitor,
    RadialCeramicDiskCapacitor,
    RadialElectrolytic,
    CopperTrace,
    Jumper,
    HookupWire,
    SolderPad,
    Label,
)
