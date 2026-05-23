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

from .core import Measure, fmt, hex_color, esc, inches, mm, cm
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
class VeroBoard(Component):
    """Stripboard / Veroboard — a perfboard with continuous copper strips.

    XML: ``<diylc.boards.VeroBoard>``

    Strip orientation is set with `orientation`: ``"HORIZONTAL"`` means strips
    run along the X axis (rows), ``"VERTICAL"`` means strips run down the Y
    axis (columns). To break a strip, place a :class:`TraceCut` on top.

    Example::

        p.add(VeroBoard("Board1", x1=1.0, y1=1.0, x2=2.2, y2=2.5))
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    alpha: int = 127
    value: str = ""
    board_color: str = "f8ebb3"
    border_color: str = "ada47d"
    strip_color: str = "da8a67"
    coordinate_color: str = "666666"
    spacing: Measure = field(default_factory=lambda: inches(0.1))
    orientation: str = "HORIZONTAL"
    x_type: str = "Numbers"
    y_type: str = "Numbers"
    coordinate_origin: str = "Top_Left"
    coordinate_display: str = "One_Side"

    __diylc_class__: ClassVar[str] = "diylc.boards.VeroBoard"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION_HV,
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
            f"{pad}<diylc.boards.VeroBoard>\n"
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
            f"{pad}  <spacing {self.spacing.attrs()}/>\n"
            f'{pad}  <stripColor hex="{hex_color(self.strip_color)}"/>\n'
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}</diylc.boards.VeroBoard>"
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
    """Parse strings like "4.7K", "470nF", "22uF" into (value, unit).

    Tolerates empty/whitespace strings by returning ``(0.0, default_unit)``
    — some round-tripped v3 files have empty value fields and we want the
    re-emit to be silent rather than crash on bad input.
    """
    import re

    if not s or not s.strip():
        return 0.0, default_unit
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
# Tubes
# ---------------------------------------------------------------------------


@dataclass
class TubeSocket(Component):
    """Tube socket — chassis or PCB mount, 7/8/9/octal/etc pin layouts.

    XML: ``<diylc.tube.TubeSocket>``

    Anchor (`x`, `y`) is the socket center. Pin positions are arranged
    around it in a circle. The number of pins comes from `base`:
    B9A=9, OCTAL=8, B7G=7. Set `type` to the tube model string
    (``"12AX7"``, ``"EL34"``, ...) — it's stored as the upstream `type`
    XML element, displayed as a label.

    Example::

        p.add(TubeSocket("V1", x=3.0, y=3.0, base="B9A", tube_type="12AX7"))
    """

    name: str
    x: float
    y: float
    base: str = "B9A"
    tube_type: str = ""  # corresponds to upstream <type> element
    angle: int = 0
    mount: str = "CHASSIS"
    alpha: int = 127
    color: str = "f7f7ef"
    label_color: str = "acaca7"
    electrode_labels: str = ""  # e.g. "1,2,3,4,5,6,7,8,9"
    pin_circle_diameter: Measure = field(default_factory=lambda: mm(20.0))

    __diylc_class__: ClassVar[str] = "diylc.tube.TubeSocket"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "base": E.TUBE_BASE,
        "mount": E.TUBE_MOUNT,
    }

    _PINS_PER_BASE: ClassVar[dict[str, int]] = {
        "B7G": 7, "B8B": 8, "B9A": 9, "OCTAL": 8,
        "MINIATURE_9": 9, "MAGNOVAL": 9, "B12C": 12, "DUODECAR": 12,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        import math

        n = self._PINS_PER_BASE[self.base]
        r = self.pin_circle_diameter.value
        if self.pin_circle_diameter.unit == "mm":
            r = r / 25.4
        elif self.pin_circle_diameter.unit == "cm":
            r = r / 2.54
        r /= 2.0
        # Start at the top and go clockwise, leaving a gap at the bottom (the
        # "key") for B9A/OCTAL conventions. Good enough for layout work.
        pts: list[Point] = []
        for i in range(n):
            theta = -math.pi / 2 + (2 * math.pi * (i + 0.5) / n)
            px = self.x + r * math.cos(theta)
            py = self.y + r * math.sin(theta)
            pts.append((round(px, 3), round(py, 3)))
        return pts

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = self._control_points()
        return (
            f"{pad}<diylc.tube.TubeSocket>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <base>{self.base}</base>\n"
            f"{pad}  <type>{esc(self.tube_type)}</type>\n"
            f"{pad}  <angle>{self.angle}</angle>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <electrodeLabels>{esc(self.electrode_labels)}</electrodeLabels>\n"
            f"{pad}  <mount>{self.mount}</mount>\n"
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f"{pad}</diylc.tube.TubeSocket>"
        )


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass
class Rectangle(Component):
    """Rectangle annotation — used for grouping or labelling regions.

    XML: ``<diylc.shapes.Rectangle>``
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = ""
    alpha: int = 95
    color: str = "ffffff"
    border_color: str = "0000ff"
    border_thickness: Measure = field(default_factory=lambda: mm(0.1))
    edge_radius: Measure = field(default_factory=lambda: mm(0.0))

    __diylc_class__: ClassVar[str] = "diylc.shapes.Rectangle"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.shapes.Rectangle>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}    <point x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f'{pad}  <firstPoint x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}  <secondPoint x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}  <borderThickness {self.border_thickness.attrs()}/>\n"
            f"{pad}  <edgeRadius {self.edge_radius.attrs()}/>\n"
            f"{pad}</diylc.shapes.Rectangle>"
        )


@dataclass
class Ellipse(Component):
    """Ellipse annotation.

    XML: ``<diylc.shapes.Ellipse>``
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = ""
    alpha: int = 127
    color: str = "ffffff"
    border_color: str = "000000"
    border_thickness: Measure = field(default_factory=lambda: mm(0.2))

    __diylc_class__: ClassVar[str] = "diylc.shapes.Ellipse"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.shapes.Ellipse>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}    <point x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f'{pad}  <firstPoint x="{fmt(self.x1)}" y="{fmt(self.y1)}"/>\n'
            f'{pad}  <secondPoint x="{fmt(self.x2)}" y="{fmt(self.y2)}"/>\n'
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}  <borderThickness {self.border_thickness.attrs()}/>\n"
            f"{pad}</diylc.shapes.Ellipse>"
        )


# ---------------------------------------------------------------------------
# Semiconductors
# ---------------------------------------------------------------------------


@dataclass
class DiodePlastic(Component):
    """Plastic-bodied through-hole diode (e.g. 1N4148, 1N400x).

    XML: ``<diylc.semiconductors.DiodePlastic>``

    Cathode is the second point (the marked band end).
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = ""
    alpha: int = 127
    body_color: str = "404040"
    border_color: str = "2c2c2c"
    label_color: str = "ffffff"
    lead_color: str = "636363"
    marker_color: str = "dddddd"
    length: Measure = field(default_factory=lambda: inches(0.2))
    width: Measure = field(default_factory=lambda: inches(0.1))
    display: str = "NAME"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.DiodePlastic"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.semiconductors.DiodePlastic>\n"
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
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f'{pad}  <markerColor hex="{hex_color(self.marker_color)}"/>\n'
            f"{pad}</diylc.semiconductors.DiodePlastic>"
        )


@dataclass
class LED(Component):
    """Through-hole LED.

    XML: ``<diylc.semiconductors.LED>``

    First point is the anode (long lead) unless `hide_short_leads=True`.
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = ""
    alpha: int = 127
    body_color: str = "ff6666"
    border_color: str = "ff0033"
    label_color: str = "000000"
    lead_color: str = "636363"
    length: Measure = field(default_factory=lambda: mm(5.0))
    width: Measure = field(default_factory=lambda: mm(5.0))
    display: str = "VALUE"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    hide_short_leads: bool = False

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.LED"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.semiconductors.LED>\n"
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
            f"{pad}  <hideShortLeads>{str(self.hide_short_leads).lower()}</hideShortLeads>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}</diylc.semiconductors.LED>"
        )


@dataclass
class TransistorTO92(Component):
    """Through-hole transistor in TO-92 package (3 pins).

    XML: ``<diylc.semiconductors.TransistorTO92>``

    Pass the position of pin 1 (`x`, `y`) and an orientation. The component
    expands to three control points along the chosen orientation, separated
    by `pin_spacing`. `pinout` describes which physical pin is E/B/C
    (or D/S/G for JFET/MOSFET) — most BJTs are BJT_EBC.

    Example::

        p.add(TransistorTO92("Q1", x=1.5, y=1.5, value="2N5088", pinout="BJT_EBC"))
    """

    name: str
    x: float
    y: float
    value: str = ""
    orientation: str = "DEFAULT"
    pinout: str = "BJT_EBC"
    pin_spacing: Measure = field(default_factory=lambda: inches(0.1))
    alpha: int = 127
    body_color: str = "404040"
    border_color: str = "2c2c2c"
    label_color: str = "ffffff"
    lead_color: str = "636363"
    display: str = "NAME"
    folded: bool = False

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.TransistorTO92"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION,
        "pinout": E.TRANSISTOR_PINOUT,
        "display": E.TRANSISTOR_DISPLAY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        # 3 pins along the orientation axis, separated by pin_spacing.
        # pin_spacing is stored as a Measure but DIYLC's editor places pins
        # at multiples of the project grid (0.1 in) — we use the numeric
        # value as inches directly, which is what the saved files do.
        s = self.pin_spacing.value
        unit = self.pin_spacing.unit
        # Convert mm/cm to inches so all components share a coord system.
        if unit == "mm":
            s = s / 25.4
        elif unit == "cm":
            s = s / 2.54
        if self.orientation == "DEFAULT":
            return [(self.x, self.y), (self.x, self.y + s), (self.x, self.y + 2 * s)]
        if self.orientation == "_90":
            return [(self.x, self.y), (self.x - s, self.y), (self.x - 2 * s, self.y)]
        if self.orientation == "_180":
            return [(self.x, self.y), (self.x, self.y - s), (self.x, self.y - 2 * s)]
        # _270
        return [(self.x, self.y), (self.x + s, self.y), (self.x + 2 * s, self.y)]

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = self._control_points()
        return (
            f"{pad}<diylc.semiconductors.TransistorTO92>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <folded>{str(self.folded).lower()}</folded>\n"
            f"{pad}  <pinout>{self.pinout}</pinout>\n"
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f"{pad}</diylc.semiconductors.TransistorTO92>"
        )


@dataclass
class DIL_IC(Component):
    """Dual-inline-package (DIP) integrated circuit.

    XML: ``<diylc.semiconductors.DIL_IC>``

    Anchor point (`x`, `y`) is pin 1 (top-left when `orientation="DEFAULT"`).

    Example::

        p.add(DIL_IC("U1", x=2.0, y=1.5, value="TL072", pin_count="_8"))
    """

    name: str
    x: float
    y: float
    value: str = ""
    pin_count: str = "_8"
    orientation: str = "DEFAULT"
    pin_spacing: Measure = field(default_factory=lambda: inches(0.1))
    row_spacing: Measure = field(default_factory=lambda: inches(0.3))
    alpha: int = 127
    body_color: str = "595959"
    border_color: str = "404040"
    label_color: str = "ffffff"
    indent_color: str = "262626"
    display_numbers: str = "DIP"

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.DIL_IC"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION,
        "pin_count": E.DIL_PIN_COUNT,
        "display_numbers": E.DIL_DISPLAY_NUMBERS,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.semiconductors.DIL_IC>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <pinCount>{self.pin_count}</pinCount>\n"
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f"{pad}  <rowSpacing {self.row_spacing.attrs()}/>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <indentColor hex="{hex_color(self.indent_color)}"/>\n'
            f"{pad}  <displayNumbers>{self.display_numbers}</displayNumbers>\n"
            f"{pad}</diylc.semiconductors.DIL_IC>"
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
class Dot(Component):
    """Small connection dot (visual marker for net junctions).

    XML: ``<diylc.connectivity.Dot>``
    """

    name: str
    x: float
    y: float
    size: Measure = field(default_factory=lambda: mm(1.0))
    color: str = "000000"

    __diylc_class__: ClassVar[str] = "diylc.connectivity.Dot"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.connectivity.Dot>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}</diylc.connectivity.Dot>"
        )


@dataclass
class Eyelet(Component):
    """Eyelet — through-hole terminal for point-to-point construction.

    XML: ``<diylc.connectivity.Eyelet>``
    """

    name: str
    x: float
    y: float
    value: str = ""
    size: Measure = field(default_factory=lambda: inches(0.2))
    hole_size: Measure = field(default_factory=lambda: inches(0.1))
    color: str = "c3e4ed"

    __diylc_class__: ClassVar[str] = "diylc.connectivity.Eyelet"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.connectivity.Eyelet>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f"{pad}  <holeSize {self.hole_size.attrs()}/>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}</diylc.connectivity.Eyelet>"
        )


@dataclass
class Turret(Component):
    """Turret terminal — a brass post for point-to-point amp wiring.

    XML: ``<diylc.connectivity.Turret>``
    """

    name: str
    x: float
    y: float
    value: str = ""
    size: Measure = field(default_factory=lambda: inches(0.16))
    hole_size: Measure = field(default_factory=lambda: inches(0.0625))
    color: str = "e0c04c"

    __diylc_class__: ClassVar[str] = "diylc.connectivity.Turret"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.connectivity.Turret>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f"{pad}  <holeSize {self.hole_size.attrs()}/>\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}</diylc.connectivity.Turret>"
        )


@dataclass
class Line(Component):
    """Straight line — used for annotations and frames.

    XML: ``<diylc.connectivity.Line>``

    Accepts a list of points; like CopperTrace, a midpoint is auto-added when
    only two are given.
    """

    name: str
    points: Sequence[Point]
    alpha: int = 127
    body_color: str = "ffffff"
    border_color: str = "000000"
    label_color: str = "000000"
    lead_color: str = "cccccc"
    display: str = "NAME"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.connectivity.Line"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()
        if len(self.points) < 2:
            raise ValueError("Line requires at least 2 points")

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = list(self.points)
        if len(pts) == 2:
            mx = (pts[0][0] + pts[1][0]) / 2.0
            my = (pts[0][1] + pts[1][1]) / 2.0
            pts = [pts[0], pts[1], (mx, my)]
        return (
            f"{pad}<diylc.connectivity.Line>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}</diylc.connectivity.Line>"
        )


@dataclass
class TraceCut(Component):
    """Break a stripboard strip at a single hole.

    XML: ``<diylc.connectivity.TraceCut>``

    Place one on each strip you want to interrupt. `orientation` should
    match the parent VeroBoard's strip orientation: ``"HORIZONTAL"`` cuts
    horizontal strips, ``"VERTICAL"`` cuts vertical ones.

    Example::

        p.add(TraceCut("C1", x=1.4, y=1.5))
    """

    name: str
    x: float
    y: float
    size: Measure = field(default_factory=lambda: inches(0.08))
    fill_color: str = "f8ebb3"
    border_color: str = "808080"
    board_color: str = "f8ebb3"
    cut_between_holes: bool = False
    orientation: str = "VERTICAL"
    hole_spacing: Measure = field(default_factory=lambda: inches(0.1))

    __diylc_class__: ClassVar[str] = "diylc.connectivity.TraceCut"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION_HV,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.connectivity.TraceCut>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f'{pad}  <fillColor hex="{hex_color(self.fill_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <boardColor hex="{hex_color(self.board_color)}"/>\n'
            f"{pad}  <cutBetweenHoles>{str(self.cut_between_holes).lower()}</cutBetweenHoles>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <holeSpacing {self.hole_spacing.attrs()}/>\n"
            f"{pad}  <controlPoints>\n"
            f'{pad}    <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  </controlPoints>\n"
            f"{pad}</diylc.connectivity.TraceCut>"
        )


@dataclass
class CurvedTrace(Component):
    """Bezier-curved copper trace with 4 control points.

    XML: ``<diylc.connectivity.CurvedTrace>``

    Pass 4 control points for a cubic Bezier curve, or 2 endpoints that get
    auto-interpolated into a gentle S-curve.

    Example::

        p.add(CurvedTrace("T1", points=[(1.0, 1.0), (2.0, 1.0)]))
    """

    name: str
    points: Sequence[Point]
    color: str = "6666ff"
    size: Measure = field(default_factory=lambda: mm(1.0))
    layer: str = "_1"
    smooth: bool = True
    alpha: int = 127
    point_count: str = "FOUR"

    __diylc_class__: ClassVar[str] = "diylc.connectivity.CurvedTrace"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "point_count": E.WIRE_POINT_COUNT,
    }

    def __post_init__(self) -> None:
        self._validate_enums()
        if len(self.points) not in (2, 4):
            raise ValueError("CurvedTrace needs 2 or 4 points")

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
            f"{pad}<diylc.connectivity.CurvedTrace>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints2', pts, indent + 2)}\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <pointCount>{self.point_count}</pointCount>\n"
            f"{pad}  <smooth>{str(self.smooth).lower()}</smooth>\n"
            f"{pad}  <lastUpdatePointIndex>-1</lastUpdatePointIndex>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f"{pad}  <layer>{self.layer}</layer>\n"
            f"{pad}</diylc.connectivity.CurvedTrace>"
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


@dataclass
class AxialFilmCapacitor(Component):
    """Axial-lead film capacitor — the cylindrical "candy" style.

    XML: ``<diylc.passive.AxialFilmCapacitor>``

    Two-pin with leads coming out the ends. Common in vintage amp builds.
    `value` accepts ``"100nF"``, ``".022uF"``. Bare numbers default to ``"nF"``.
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
    lead_color: str = "cccccc"
    length: Measure = field(default_factory=lambda: mm(16.0))
    width: Measure = field(default_factory=lambda: mm(7.0))
    display: str = "BOTH"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.AxialFilmCapacitor"
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
            f"{pad}<diylc.passive.AxialFilmCapacitor>\n"
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
            f"{pad}</diylc.passive.AxialFilmCapacitor>"
        )


@dataclass
class AxialElectrolyticCapacitor(Component):
    """Axial-lead electrolytic capacitor — leads coming out both ends.

    XML: ``<diylc.passive.AxialElectrolyticCapacitor>``

    First point is the positive lead unless ``invert=True``. Common in
    vintage tube amps for cathode bypass.
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "10uF"
    voltage: str = "_63V"
    alpha: int = 127
    body_color: str = "6b6dce"
    border_color: str = "4a4c90"
    label_color: str = "ffffff"
    lead_color: str = "cccccc"
    marker_color: str = "8cacea"
    tick_color: str = "ffffff"
    length: Measure = field(default_factory=lambda: mm(17.5))
    width: Measure = field(default_factory=lambda: mm(6.4))
    display: str = "BOTH"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    polarized: bool = True
    invert: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.AxialElectrolyticCapacitor"
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
            f"{pad}<diylc.passive.AxialElectrolyticCapacitor>\n"
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
            f'{pad}  <markerColor hex="{hex_color(self.marker_color)}"/>\n'
            f'{pad}  <tickColor hex="{hex_color(self.tick_color)}"/>\n'
            f"{pad}  <polarized>{str(self.polarized).lower()}</polarized>\n"
            f"{pad}</diylc.passive.AxialElectrolyticCapacitor>"
        )


@dataclass
class PotentiometerPanel(Component):
    """Panel-mount potentiometer with three lug terminals.

    XML: ``<diylc.passive.PotentiometerPanel>``

    Anchor point (`x`, `y`) is the position of lug 1. The other two lugs
    follow along the orientation axis at `spacing` apart. `resistance` is a
    string like ``"100K"``, ``"1M"``, ``"10K"``; bare numbers default to
    ``"K"``.

    Example::

        p.add(PotentiometerPanel("VR1", x=1.0, y=4.0, resistance="100K", taper="LOG"))
    """

    name: str
    x: float
    y: float
    resistance: str = "100K"
    orientation: str = "DEFAULT"
    taper: str = "LIN"
    type: str = "ThroughHole"
    view: str = "ShaftDown"
    alpha: int = 127
    body_color: str = "b6b6b6"
    border_color: str = "808080"
    wafer_color: str = "cd8500"
    body_diameter: Measure = field(default_factory=lambda: mm(17.0))
    spacing: Measure = field(default_factory=lambda: inches(0.2))
    lug_diameter: Measure = field(default_factory=lambda: inches(0.15))
    show_shaft: bool = False

    __diylc_class__: ClassVar[str] = "diylc.passive.PotentiometerPanel"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION,
        "taper": E.POT_TAPER,
        "type": E.POT_TYPE,
        "view": E.POT_VIEW,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        s = self.spacing.value
        if self.spacing.unit == "mm":
            s = s / 25.4
        elif self.spacing.unit == "cm":
            s = s / 2.54
        if self.orientation == "DEFAULT":  # horizontal, lugs left to right
            return [(self.x, self.y), (self.x - s, self.y), (self.x - 2 * s, self.y)]
        if self.orientation == "_90":  # vertical, lugs top to bottom
            return [(self.x, self.y), (self.x, self.y + s), (self.x, self.y + 2 * s)]
        if self.orientation == "_180":  # horizontal, lugs right to left
            return [(self.x, self.y), (self.x + s, self.y), (self.x + 2 * s, self.y)]
        return [(self.x, self.y), (self.x, self.y - s), (self.x, self.y - 2 * s)]

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.resistance, default_unit="K")
        pts = self._control_points()
        return (
            f"{pad}<diylc.passive.PotentiometerPanel>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f'{pad}  <resistance value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <taper>{self.taper}</taper>\n"
            f"{pad}  <bodyDiameter {self.body_diameter.attrs()}/>\n"
            f"{pad}  <spacing {self.spacing.attrs()}/>\n"
            f"{pad}  <lugDiameter {self.lug_diameter.attrs()}/>\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <waferColor hex="{hex_color(self.wafer_color)}"/>\n'
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}  <showShaft>{str(self.show_shaft).lower()}</showShaft>\n"
            f"{pad}  <view>{self.view}</view>\n"
            f"{pad}</diylc.passive.PotentiometerPanel>"
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


@dataclass
class TrimmerPotentiometer(Component):
    """Small board-mount trimmer pot (3-pin).

    XML: ``<diylc.passive.TrimmerPotentiometer>``

    Anchor (`x`, `y`) is lug 1. The geometry of the other lugs depends on
    `type` (horizontal flat package vs. vertical can). ``resistance`` accepts
    strings like ``"10K"``, ``"100K"``; bare numbers default to ``"K"``.

    Example::

        p.add(TrimmerPotentiometer("BIAS", x=2.0, y=1.0, resistance="10K"))
    """

    name: str
    x: float
    y: float
    resistance: str = "10K"
    orientation: str = "DEFAULT"
    taper: str = "LIN"
    type: str = "FLAT_SMALL"
    alpha: int = 127
    body_color: str = "ffffe0"
    border_color: str = "8e8e38"
    display: str = "BOTH"

    __diylc_class__: ClassVar[str] = "diylc.passive.TrimmerPotentiometer"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION,
        "taper": E.POT_TAPER,
        "type": E.TRIMMER_TYPE,
        "display": E.DISPLAY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        # 3 lugs: 2 along one row, 1 offset perpendicular (the wiper).
        # Use 0.1 in pin spacing — standard for FLAT_* packages.
        s = 0.1
        if self.orientation in ("DEFAULT", "_180"):
            sign = 1 if self.orientation == "DEFAULT" else -1
            return [
                (self.x, self.y),
                (self.x + sign * 2 * s, self.y + sign * s),
                (self.x, self.y + sign * 2 * s),
            ]
        sign = 1 if self.orientation == "_90" else -1
        return [
            (self.x, self.y),
            (self.x + sign * s, self.y + sign * 2 * s),
            (self.x + sign * 2 * s, self.y),
        ]

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.resistance, default_unit="K")
        pts = self._control_points()
        return (
            f"{pad}<diylc.passive.TrimmerPotentiometer>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f'{pad}  <resistance value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <taper>{self.taper}</taper>\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}</diylc.passive.TrimmerPotentiometer>"
        )


@dataclass
class TerminalStrip(Component):
    """Terminal strip — multiple turret-style terminals on a board.

    XML: ``<diylc.boards.TerminalStrip>``

    Anchor (`x`, `y`) is the first terminal. The strip extends along the
    orientation axis. `terminal_count` is the number of terminals per row;
    the strip has 2 rows by default (top terminals + bottom mounting holes).
    """

    name: str
    x: float
    y: float
    value: str = ""
    orientation: str = "DEFAULT"
    terminal_count: int = 3
    alpha: int = 127
    body_color: str = "cd8500"
    border_color: str = "8f5d00"
    board_width: Measure = field(default_factory=lambda: inches(0.2))
    terminal_spacing: Measure = field(default_factory=lambda: inches(0.2))
    hole_spacing: Measure = field(default_factory=lambda: inches(0.3))
    center_hole: bool = False

    __diylc_class__: ClassVar[str] = "diylc.boards.TerminalStrip"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "orientation": E.ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        spacing = _to_inches(self.terminal_spacing)
        hole = _to_inches(self.hole_spacing)
        pts: list[Point] = []
        if self.orientation in ("DEFAULT", "_180"):
            sign = 1 if self.orientation == "DEFAULT" else -1
            # Top row (terminals)
            for i in range(self.terminal_count):
                pts.append((self.x + sign * i * spacing, self.y))
            # Bottom row (mounting holes)
            for i in range(self.terminal_count):
                pts.append((self.x + sign * i * spacing, self.y - sign * hole))
        else:
            sign = 1 if self.orientation == "_90" else -1
            for i in range(self.terminal_count):
                pts.append((self.x, self.y + sign * i * spacing))
            for i in range(self.terminal_count):
                pts.append((self.x + sign * hole, self.y + sign * i * spacing))
        return pts

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = self._control_points()
        return (
            f"{pad}<diylc.boards.TerminalStrip>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <terminalCount>{self.terminal_count}</terminalCount>\n"
            f"{pad}  <boardWidth {self.board_width.attrs()}/>\n"
            f"{pad}  <terminalSpacing {self.terminal_spacing.attrs()}/>\n"
            f"{pad}  <holeSpacing {self.hole_spacing.attrs()}/>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f'{pad}  <boardColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}  <centerHole>{str(self.center_hole).lower()}</centerHole>\n"
            f"{pad}</diylc.boards.TerminalStrip>"
        )


@dataclass
class Image(Component):
    """Embedded raster image annotation.

    XML: ``<diylc.misc.Image>``

    Holds a base64-encoded PNG/JPEG blob. pydiylc passes the data through
    unmodified on read; emitting requires the caller to provide ``data`` as
    a base64 string (no MIME prefix).
    """

    name: str
    x: float
    y: float
    data: str = ""
    alpha: int = 127

    __diylc_class__: ClassVar[str] = "diylc.misc.Image"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.misc.Image>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f"{pad}  <data>{esc(self.data)}</data>\n"
            f"{pad}</diylc.misc.Image>"
        )


@dataclass
class BOM(Component):
    """Bill of materials placeholder — DIYLC autopopulates this at render time.

    XML: ``<diylc.misc.BOM>``

    No fields beyond name, position, color, size. The BOM contents are
    derived from the project's other components.
    """

    name: str
    x: float
    y: float
    size: Measure = field(default_factory=lambda: cm(5.0))
    color: str = "000000"

    __diylc_class__: ClassVar[str] = "diylc.misc.BOM"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.misc.BOM>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <size {self.size.attrs()}/>\n"
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}</diylc.misc.BOM>"
        )


def _to_inches(m: Measure) -> float:
    if m.unit == "in":
        return m.value
    if m.unit == "mm":
        return m.value / 25.4
    if m.unit == "cm":
        return m.value / 2.54
    return m.value


# ---------------------------------------------------------------------------
# Schematic symbols
# ---------------------------------------------------------------------------


@dataclass
class ResistorSymbol(Component):
    """Schematic-style resistor symbol (zigzag or rectangle).

    XML: ``<diylc.passive.ResistorSymbol>``

    Two-point symbol. `value` accepts ``"470K"``, ``"10K"`` etc. Bare numbers
    default to ``"K"``.
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "10K"
    power: str = "HALF"
    alpha: int = 127
    border_color: str = "0000ff"
    label_color: str = "000000"
    lead_color: str = "000000"
    length: Measure = field(default_factory=lambda: inches(0.3))
    width: Measure = field(default_factory=lambda: inches(0.08))
    display: str = "NAME"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    label_position: str = "ABOVE"

    __diylc_class__: ClassVar[str] = "diylc.passive.ResistorSymbol"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "power": E.POWER,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
        "label_position": E.LABEL_POSITION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="K")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.ResistorSymbol>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <labelPosition>{self.label_position}</labelPosition>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <power>{self.power}</power>\n"
            f"{pad}</diylc.passive.ResistorSymbol>"
        )


@dataclass
class CapacitorSymbol(Component):
    """Schematic-style capacitor symbol (parallel plates).

    XML: ``<diylc.passive.CapacitorSymbol>``
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "100nF"
    voltage: str = "_63V"
    polarized: bool = False
    alpha: int = 127
    border_color: str = "0000ff"
    label_color: str = "000000"
    lead_color: str = "000000"
    length: Measure = field(default_factory=lambda: inches(0.05))
    width: Measure = field(default_factory=lambda: inches(0.15))
    display: str = "NAME"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    label_position: str = "ABOVE"

    __diylc_class__: ClassVar[str] = "diylc.passive.CapacitorSymbol"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "voltage": E.VOLTAGE,
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
        "label_position": E.LABEL_POSITION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit="nF")
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.passive.CapacitorSymbol>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <labelPosition>{self.label_position}</labelPosition>\n"
            f'{pad}  <value value="{fmt(val)}" unit="{unit}"/>\n'
            f"{pad}  <voltage>{self.voltage}</voltage>\n"
            f"{pad}  <polarized>{str(self.polarized).lower()}</polarized>\n"
            f"{pad}</diylc.passive.CapacitorSymbol>"
        )


@dataclass
class DiodeSymbol(Component):
    """Schematic-style diode symbol (triangle + bar).

    XML: ``<diylc.semiconductors.DiodeSymbol>``

    First point is anode, second point is cathode.
    """

    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = ""
    alpha: int = 127
    body_color: str = "0000ff"
    label_color: str = "000000"
    lead_color: str = "000000"
    length: Measure = field(default_factory=lambda: inches(0.1))
    width: Measure = field(default_factory=lambda: inches(0.1))
    display: str = "NAME"
    flip_standing: bool = False
    label_orientation: str = "Directional"
    move_label: bool = False
    label_position: str = "ABOVE"

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.DiodeSymbol"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "display": E.DISPLAY,
        "label_orientation": E.LABEL_ORIENTATION,
        "label_position": E.LABEL_POSITION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        return (
            f"{pad}<diylc.semiconductors.DiodeSymbol>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{pad}  <length {self.length.attrs()}/>\n"
            f"{pad}  <width {self.width.attrs()}/>\n"
            f"{_points_block('points', pts, indent + 2)}\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <labelColor hex="{hex_color(self.label_color)}"/>\n'
            f'{pad}  <leadColor hex="{hex_color(self.lead_color)}"/>\n'
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <flipStanding>{str(self.flip_standing).lower()}</flipStanding>\n"
            f"{pad}  <labelOriantation>{self.label_orientation}</labelOriantation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <labelPosition>{self.label_position}</labelPosition>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}</diylc.semiconductors.DiodeSymbol>"
        )


@dataclass
class BJTSymbol(Component):
    """Schematic-style BJT transistor symbol.

    XML: ``<diylc.semiconductors.BJTSymbol>``

    Anchor (`x`, `y`) is the base lead. The collector and emitter points are
    placed automatically based on `orientation`. `polarity` toggles between
    NPN (arrow out) and PNP (arrow in).
    """

    name: str
    x: float
    y: float
    value: str = ""
    polarity: str = "NPN"
    orientation: str = "DEFAULT"
    flip: str = "NONE"
    display: str = "BOTH"
    color: str = "000000"
    move_label: bool = False

    __diylc_class__: ClassVar[str] = "diylc.semiconductors.BJTSymbol"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "polarity": E.BJT_POLARITY,
        "orientation": E.ORIENTATION,
        "flip": E.SYMBOL_FLIPPING,
        "display": E.DISPLAY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        # 4 control points: base, collector, emitter, label-anchor (~center).
        # Placement here is a sane default; DIYLC stores actual rendered
        # positions but we re-derive on emit.
        if self.orientation == "DEFAULT":
            base = (self.x, self.y)
            col = (self.x + 0.2, self.y - 0.2)
            emi = (self.x + 0.2, self.y + 0.2)
            lbl = (self.x + 0.15, self.y)
        elif self.orientation == "_90":
            base = (self.x, self.y)
            col = (self.x + 0.2, self.y + 0.2)
            emi = (self.x - 0.2, self.y + 0.2)
            lbl = (self.x, self.y + 0.15)
        elif self.orientation == "_180":
            base = (self.x, self.y)
            col = (self.x - 0.2, self.y + 0.2)
            emi = (self.x - 0.2, self.y - 0.2)
            lbl = (self.x - 0.15, self.y)
        else:  # _270
            base = (self.x, self.y)
            col = (self.x - 0.2, self.y - 0.2)
            emi = (self.x + 0.2, self.y - 0.2)
            lbl = (self.x, self.y - 0.15)
        return [base, col, emi, lbl]

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = self._control_points()
        return (
            f"{pad}<diylc.semiconductors.BJTSymbol>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <flip>{self.flip}</flip>\n"
            f"{pad}  <display>{self.display}</display>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <moveLabel>{str(self.move_label).lower()}</moveLabel>\n"
            f"{pad}  <polarity>{self.polarity}</polarity>\n"
            f"{pad}</diylc.semiconductors.BJTSymbol>"
        )


@dataclass
class GroundSymbol(Component):
    """Schematic ground symbol (single-point reference to ground).

    XML: ``<diylc.misc.GroundSymbol>``
    """

    name: str
    x: float
    y: float
    type: str = "DEFAULT"
    color: str = "000000"
    size: Measure = field(default_factory=lambda: inches(0.15))

    __diylc_class__: ClassVar[str] = "diylc.misc.GroundSymbol"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "type": E.GROUND_SYMBOL_TYPE,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        return (
            f"{pad}<diylc.misc.GroundSymbol>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f'{pad}  <point x="{fmt(self.x)}" y="{fmt(self.y)}"/>\n'
            f'{pad}  <color hex="{hex_color(self.color)}"/>\n'
            f"{pad}  <size {self.size.attrs()}/>\n"
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}</diylc.misc.GroundSymbol>"
        )


# ---------------------------------------------------------------------------
# Electromechanical
# ---------------------------------------------------------------------------


@dataclass
class MiniToggleSwitch(Component):
    """Mini toggle switch — also covers 3PDT pedal foot switches.

    XML: ``<diylc.electromechanical.MiniToggleSwitch>``

    Anchor (`x`, `y`) is lug 1. Remaining lugs lay out along the orientation
    axis based on `switch_type` (pole count) — 2 lugs for SPST, 6 for DPDT,
    9 for 3PDT, 12 for 4PDT, 15 for 5PDT. For a bypass 3PDT use
    ``switch_type="_3PDT"``.

    Example::

        p.add(MiniToggleSwitch("SW1", x=2.0, y=4.0, switch_type="_3PDT"))
    """

    name: str
    x: float
    y: float
    switch_type: str = "DPDT"
    orientation: str = "VERTICAL"
    spacing: Measure = field(default_factory=lambda: inches(0.2))
    alpha: int = 127
    body_color: str = "3299cc"
    border_color: str = "236b8e"

    __diylc_class__: ClassVar[str] = "diylc.electromechanical.MiniToggleSwitch"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "switch_type": E.TOGGLE_SWITCH_TYPE,
        "orientation": E.ORIENTATION_HV,
    }

    _LUG_COUNT_BY_TYPE: ClassVar[dict[str, int]] = {
        "SPST": 2,
        "SPDT": 3, "SPDT_off": 3,
        "DPDT": 6, "DPDT_off": 6, "DPDT_ononon_1": 6, "DPDT_ononon_2": 6,
        "_3PDT": 9, "_3PDT_off": 9,
        "_4PDT": 12, "_4PDT_off": 12, "_4PDT_ononon_1": 12, "_4PDT_ononon_2": 12,
        "_5PDT": 15, "_5PDT_off": 15,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def _control_points(self) -> list[Point]:
        # Switches are wired in 2- or 3-row grids. Convert spacing to inches.
        s = self.spacing.value
        if self.spacing.unit == "mm":
            s = s / 25.4
        elif self.spacing.unit == "cm":
            s = s / 2.54
        n = self._LUG_COUNT_BY_TYPE[self.switch_type]
        # Pole count = ceil(n/positions_per_pole); for our purposes lay out
        # n lugs in a single column at `spacing` apart along orientation.
        # DIYLC's editor splits poles across rows visually, but the saved
        # control points are a flat list — one per lug.
        pts: list[Point] = []
        for i in range(n):
            if self.orientation == "VERTICAL":
                pts.append((self.x, self.y + i * s))
            else:
                pts.append((self.x + i * s, self.y))
        return pts

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = self._control_points()
        return (
            f"{pad}<diylc.electromechanical.MiniToggleSwitch>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f"{pad}  <switchType>{self.switch_type}</switchType>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <spacing {self.spacing.attrs()}/>\n"
            f'{pad}  <bodyColor hex="{hex_color(self.body_color)}"/>\n'
            f'{pad}  <borderColor hex="{hex_color(self.border_color)}"/>\n'
            f"{pad}</diylc.electromechanical.MiniToggleSwitch>"
        )


@dataclass
class PlasticDCJack(Component):
    """Plastic 2.1mm DC barrel jack (the "Boss-style" power input).

    XML: ``<diylc.electromechanical.PlasticDCJack>``

    Three terminals: tip, sleeve, and switch contact. Anchor is the tip lug.
    """

    name: str
    x: float
    y: float
    value: str = ""
    polarity: str = "CENTER_NEGATIVE"
    alpha: int = 127

    __diylc_class__: ClassVar[str] = "diylc.electromechanical.PlasticDCJack"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "polarity": E.DC_POLARITY,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        # DIYLC stores 3 control points (tip, sleeve, switch) relative to anchor.
        # 0.1 in offsets approximate a typical Boss-style jack footprint.
        pts: list[Point] = [
            (self.x, self.y),
            (self.x + 0.1, self.y + 0.1),
            (self.x - 0.1, self.y + 0.2),
        ]
        return (
            f"{pad}<diylc.electromechanical.PlasticDCJack>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <polarity>{self.polarity}</polarity>\n"
            f"{pad}</diylc.electromechanical.PlasticDCJack>"
        )


@dataclass
class OpenJack1_4(Component):
    """Open-frame 1/4" audio jack — the standard "Switchcraft 11"-style guitar jack.

    XML: ``<diylc.electromechanical.OpenJack1_4>``

    Anchor is the tip lug. Use `type="MONO"` for input, `"STEREO"` for
    stereo, `"SWITCHED"` for an input jack that disconnects ground when
    no plug is inserted (battery save on pedals).
    """

    name: str
    x: float
    y: float
    value: str = ""
    type: str = "MONO"
    orientation: str = "DEFAULT"
    angle: int = 0
    show_labels: bool = True
    alpha: int = 127

    __diylc_class__: ClassVar[str] = "diylc.electromechanical.OpenJack1_4"
    __enums__: ClassVar[dict[str, tuple[str, ...]]] = {
        "type": E.OPEN_JACK_TYPE,
        "orientation": E.ORIENTATION,
    }

    def __post_init__(self) -> None:
        self._validate_enums()

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        # 3 control points: tip, sleeve, (ring/switch). Use 0.1 in offsets.
        pts: list[Point] = [
            (self.x, self.y),
            (self.x, self.y + 0.1),
            (self.x, self.y + 0.2),
        ]
        return (
            f"{pad}<diylc.electromechanical.OpenJack1_4>\n"
            f"{pad}  <name>{esc(self.name)}</name>\n"
            f"{pad}  <alpha>{self.alpha}</alpha>\n"
            f"{_points_block('controlPoints', pts, indent + 2)}\n"
            f"{pad}  <value>{esc(self.value)}</value>\n"
            f"{pad}  <orientation>{self.orientation}</orientation>\n"
            f"{pad}  <angle>{self.angle}</angle>\n"
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}  <showLabels>{str(self.show_labels).lower()}</showLabels>\n"
            f"{pad}</diylc.electromechanical.OpenJack1_4>"
        )


# Public registry of every Component subclass — used by `pydiylc.catalog`
# to build the machine-readable schema.
ALL_COMPONENTS: tuple[type[Component], ...] = (
    BlankBoard,
    PerfBoard,
    VeroBoard,
    Resistor,
    RadialFilmCapacitor,
    RadialCeramicDiskCapacitor,
    RadialElectrolytic,
    AxialFilmCapacitor,
    AxialElectrolyticCapacitor,
    PotentiometerPanel,
    TrimmerPotentiometer,
    ResistorSymbol,
    CapacitorSymbol,
    TubeSocket,
    Rectangle,
    Ellipse,
    DiodePlastic,
    LED,
    TransistorTO92,
    DIL_IC,
    DiodeSymbol,
    BJTSymbol,
    CopperTrace,
    CurvedTrace,
    Jumper,
    HookupWire,
    SolderPad,
    Dot,
    Eyelet,
    Turret,
    Line,
    TraceCut,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
    TerminalStrip,
    Label,
    Image,
    BOM,
    GroundSymbol,
)
