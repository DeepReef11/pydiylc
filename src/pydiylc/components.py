from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .core import Measure, fmt, hex_color, esc, inches, mm


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
    """Base — subclasses override `to_xml(indent)`."""

    def to_xml(self, indent: int = 4) -> str:  # pragma: no cover - interface
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


@dataclass
class BlankBoard(Component):
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

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        bc = hex_color(self.board_color)
        bd = hex_color(self.border_color)
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
            f'{pad}  <boardColor hex="{bc}"/>\n'
            f'{pad}  <borderColor hex="{bd}"/>\n'
            f"{pad}  <mode>TwoPoints</mode>\n"
            f"{pad}  <type>{self.type}</type>\n"
            f"{pad}</diylc.boards.BlankBoard>"
        )


@dataclass
class PerfBoard(Component):
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
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str = "1K"  # "1K", "4.7K", "10K", "1M"
    power: str = "HALF"  # QUARTER | HALF | ONE | TWO
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
    """Parse strings like "4.7K", "470nF", "22uF", "10pF" into (value, unit).

    Recognized R/C unit suffixes are passed through. If the string is a bare
    number, default_unit is used.
    """
    import re

    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]+)?\s*$", s)
    if not m:
        raise ValueError(f"can't parse value: {s!r}")
    num = float(m.group(1))
    unit = m.group(2) or default_unit
    return num, unit


@dataclass
class _RadialCapBase(Component):
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str  # e.g. "470nF", "22uF", "1000pF"
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

    _tag: str = ""  # set by subclass
    _default_unit: str = "nF"
    _extra: str = ""  # subclass-specific extra elements (raw XML)

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        val, unit = _split_value(self.value, default_unit=self._default_unit)
        pts = _two_point_with_mid((self.x1, self.y1), (self.x2, self.y2))
        extra = ""
        if self._extra:
            extra = "\n".join(f"{pad}  {ln}" for ln in self._extra.splitlines()) + "\n"
        return (
            f"{pad}<{self._tag}>\n"
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
            f"{pad}  <pinSpacing {self.pin_spacing.attrs()}/>\n"
            f"{extra}"
            f"{pad}</{self._tag}>"
        )


@dataclass
class RadialFilmCapacitor(_RadialCapBase):
    show_outer_foil: bool = False
    _tag: str = "diylc.passive.RadialFilmCapacitor"
    _default_unit: str = "nF"

    def to_xml(self, indent: int = 4) -> str:
        self._extra = f"<showOuterFoil>{str(self.show_outer_foil).lower()}</showOuterFoil>"
        return super().to_xml(indent)


@dataclass
class RadialCeramicDiskCapacitor(_RadialCapBase):
    body_color: str = "f0e68c"
    border_color: str = "a8a162"
    length: Measure = field(default_factory=lambda: inches(0.4))
    width: Measure = field(default_factory=lambda: inches(0.125))
    _tag: str = "diylc.passive.RadialCeramicDiskCapacitor"
    _default_unit: str = "pF"


@dataclass
class RadialElectrolytic(Component):
    name: str
    x1: float
    y1: float
    x2: float
    y2: float
    value: str  # e.g. "22uF"
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

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        if len(self.points) < 2:
            raise ValueError("CopperTrace requires at least 2 points")
        pts = list(self.points)
        if len(pts) == 2:  # add midpoint, like DIYLC
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
    name: str
    points: Sequence[Point]  # exactly 4 control points (Bezier-ish)
    color: str = "000000"
    gauge: str = "_22"  # AWG: _20, _22, _24
    style: str = "SOLID"
    striped: bool = False
    smooth: bool = True
    alpha: int = 127
    point_count: str = "FOUR"

    def to_xml(self, indent: int = 4) -> str:
        pad = _indent(indent)
        pts = list(self.points)
        if len(pts) == 2:
            # interpolate two intermediate control points along the segment
            (x1, y1), (x2, y2) = pts
            pts = [
                (x1, y1),
                (x1 + (x2 - x1) / 3.0, y1 + (y2 - y1) / 3.0),
                (x1 + 2 * (x2 - x1) / 3.0, y1 + 2 * (y2 - y1) / 3.0),
                (x2, y2),
            ]
        if len(pts) != 4:
            raise ValueError("HookupWire needs 2 or 4 points")
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
    name: str
    x: float
    y: float
    size: Measure = field(default_factory=lambda: mm(3.0))
    color: str = "000000"
    type: str = "ROUND"  # ROUND | SQUARE
    hole_size: Measure = field(default_factory=lambda: mm(0.8))

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
    name: str
    x: float
    y: float
    text: str
    font: str = "Tahoma"
    font_size: int = 14
    font_style: int = 0  # 0=plain, 1=bold, 2=italic, 3=bold-italic
    color: str = "000000"
    center: bool = True
    horizontal_alignment: str = "CENTER"
    vertical_alignment: str = "CENTER"
    orientation: str = "DEFAULT"

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
