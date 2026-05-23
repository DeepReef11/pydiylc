"""Native SVG renderer for pydiylc Projects.

This produces a quick-preview SVG that gets *shape, position, and color* right
for every component pydiylc knows about. It is NOT pixel-identical to DIYLC's
own renderer — that would require reimplementing thousands of lines of Java
drawing code. The intent is fast feedback while iterating on a layout, and
later a base for an interactive viewer.

For high-fidelity output, run DIYLC headless on the saved .diy file::

    diylc -convert layout.diy layout.png

Usage::

    from pydiylc import Project
    from pydiylc.svg import render_svg

    p = Project(...)
    p.add(...)
    svg = render_svg(p)
    Path("layout.svg").write_text(svg)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape as _esc

from .core import Project, Measure
from .components import (
    Component,
    AxialFilmCapacitor,
    AxialElectrolyticCapacitor,
    BJTSymbol,
    BlankBoard,
    BOM,
    CapacitorSymbol,
    CliffJack1_4,
    ClosedJack1_4,
    CurvedTrace,
    DiodeGlass,
    DiodeSymbol,
    Dot,
    Ellipse,
    EllipticalCutout,
    Eyelet,
    GroundFill,
    GroundSymbol,
    Image,
    Line,
    PCBText,
    PerfBoard,
    PinHeader,
    Polygon,
    PotentiometerSymbol,
    RCAJack,
    Rectangle,
    ResistorSymbol,
    SingleCoilPickup,
    TerminalStrip,
    TransformerCoil,
    TransformerCore,
    TrimmerPotentiometer,
    TriodeSymbol,
    TubeSocket,
    Turret,
    VeroBoard,
    WrapLabel,
    TagStrip,
    PilotLampHolder,
    MultiSectionCapacitor,
    TapeMeasure,
    FuseHolderPanel,
    AudioTransformer,
    LEDSymbol,
    SIL_IC,
    ChassisPanel,
    TransistorTO1,
    Resistor,
    RadialFilmCapacitor,
    RadialCeramicDiskCapacitor,
    RadialElectrolytic,
    PotentiometerPanel,
    DiodePlastic,
    LED,
    TransistorTO92,
    DIL_IC,
    CopperTrace,
    Jumper,
    HookupWire,
    SolderPad,
    TraceCut,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
    Label,
)


# DIYLC's editor uses 1 in = 96 px (CSS pixel). Keep that to match exported
# images at standard resolution.
PX_PER_INCH = 96.0


@dataclass(frozen=True)
class RenderOptions:
    px_per_inch: float = PX_PER_INCH
    pad_px: float = 8.0  # margin around content
    background: str = "#ffffff"
    show_grid: bool = True
    grid_color: str = "#e8e8e8"
    grid_inches: float = 0.1


def _measure_to_inches(m: Measure) -> float:
    if m.unit == "in":
        return m.value
    if m.unit == "mm":
        return m.value / 25.4
    if m.unit == "cm":
        return m.value / 2.54
    if m.unit == "px":
        return m.value / PX_PER_INCH
    return m.value  # unknown unit — best effort


def _color(hex6: str) -> str:
    return f"#{hex6.lstrip('#').lower()}"


def render_svg(project: Project, options: RenderOptions | None = None) -> str:
    """Render a Project to an SVG string."""
    opts = options or RenderOptions()
    scale = opts.px_per_inch
    pad = opts.pad_px

    # The DIYLC project canvas is the project's width_cm/height_cm.
    w_in = project.width_cm / 2.54
    h_in = project.height_cm / 2.54
    w_px = w_in * scale + 2 * pad
    h_px = h_in * scale + 2 * pad

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w_px:.1f}" height="{h_px:.1f}" '
        f'viewBox="0 0 {w_px:.1f} {h_px:.1f}" '
        f'font-family="sans-serif">'
    )
    parts.append(f'<rect width="{w_px:.1f}" height="{h_px:.1f}" fill="{opts.background}"/>')

    if opts.show_grid:
        parts.append(_grid(w_in, h_in, scale, pad, opts))

    parts.append(f'<g transform="translate({pad},{pad})">')
    for component in project.components:
        try:
            parts.append(_render_one(component, scale))
        except Exception as exc:  # never let a bad component break the whole SVG
            parts.append(_error_marker(component, scale, exc))
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts)


def render_svg_file(project: Project, path) -> None:
    """Convenience: render and write to disk."""
    from pathlib import Path

    Path(path).write_text(render_svg(project), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _grid(w_in: float, h_in: float, scale: float, pad: float, opts: RenderOptions) -> str:
    g = opts.grid_inches
    lines: list[str] = ['<g stroke="' + opts.grid_color + '" stroke-width="0.5">']
    n_x = int(w_in / g) + 1
    n_y = int(h_in / g) + 1
    for i in range(n_x + 1):
        x = pad + i * g * scale
        lines.append(
            f'<line x1="{x:.1f}" y1="{pad:.1f}" x2="{x:.1f}" y2="{pad + h_in * scale:.1f}"/>'
        )
    for i in range(n_y + 1):
        y = pad + i * g * scale
        lines.append(
            f'<line x1="{pad:.1f}" y1="{y:.1f}" x2="{pad + w_in * scale:.1f}" y2="{y:.1f}"/>'
        )
    lines.append("</g>")
    return "\n".join(lines)


def _error_marker(component: Component, scale: float, exc: Exception) -> str:
    name = getattr(component, "name", "?")
    return (
        f'<g><!-- error rendering {_esc(type(component).__name__)} '
        f'{_esc(name)}: {_esc(str(exc))} --></g>'
    )


def _render_one(c: Component, s: float) -> str:
    handler = _RENDERERS.get(type(c))
    if handler is None:
        # Generic fallback: small marker at the first coord we can find
        return _fallback(c, s)
    return handler(c, s)


def _fallback(c: Component, s: float) -> str:
    x = getattr(c, "x", None) or getattr(c, "x1", 0.0)
    y = getattr(c, "y", None) or getattr(c, "y1", 0.0)
    name = getattr(c, "name", "?")
    return (
        f'<g><circle cx="{x*s:.1f}" cy="{y*s:.1f}" r="4" '
        f'fill="none" stroke="#888" stroke-dasharray="2,2"/>'
        f'<text x="{x*s+6:.1f}" y="{y*s+4:.1f}" font-size="8" fill="#888">{_esc(name)}</text></g>'
    )


# ---------------------------------------------------------------------------
# Per-component renderers
# ---------------------------------------------------------------------------


def _board(c, s, *, stripe_orientation: str | None = None, stripe_color: str | None = None) -> str:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    out = [
        f'<g class="board" data-name="{_esc(c.name)}">',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{_color(c.board_color)}" stroke="{_color(c.border_color)}" stroke-width="1"/>',
    ]
    # Strip overlay for VeroBoard
    if stripe_orientation is not None and stripe_color is not None:
        spacing_in = _measure_to_inches(c.spacing)
        step = spacing_in * s
        if stripe_orientation == "HORIZONTAL":
            ny = max(1, int(h / step))
            for i in range(ny):
                cy = y + (i + 0.5) * step
                out.append(
                    f'<line x1="{x:.1f}" y1="{cy:.1f}" x2="{x+w:.1f}" y2="{cy:.1f}" '
                    f'stroke="{_color(stripe_color)}" stroke-width="3" opacity="0.55"/>'
                )
        else:
            nx = max(1, int(w / step))
            for i in range(nx):
                cx = x + (i + 0.5) * step
                out.append(
                    f'<line x1="{cx:.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{y+h:.1f}" '
                    f'stroke="{_color(stripe_color)}" stroke-width="3" opacity="0.55"/>'
                )
    # Pad grid for PerfBoard
    if isinstance(c, PerfBoard):
        spacing_in = _measure_to_inches(c.spacing)
        step = spacing_in * s
        nx = int(w / step) + 1
        ny = int(h / step) + 1
        for i in range(nx):
            for j in range(ny):
                cx = x + i * step
                cy = y + j * step
                out.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.6" '
                    f'fill="{_color(c.pad_color)}"/>'
                )
    out.append("</g>")
    return "\n".join(out)


def _render_blank_board(c: BlankBoard, s: float) -> str:
    return _board(c, s)


def _render_perf_board(c: PerfBoard, s: float) -> str:
    return _board(c, s)


def _render_vero_board(c: VeroBoard, s: float) -> str:
    return _board(c, s, stripe_orientation=c.orientation, stripe_color=c.strip_color)


def _two_pin_lead(p1: tuple[float, float], p2: tuple[float, float], s: float,
                  *, body_frac: float = 0.55, lead_color: str = "#636363",
                  body_w_in: float = 0.1, body_color: str = "#82cffd",
                  border_color: str = "#5b90b1") -> list[str]:
    """Draw a horizontal/vertical 2-pin component as leads + a centered body rect."""
    import math

    x1, y1 = p1[0] * s, p1[1] * s
    x2, y2 = p2[0] * s, p2[1] * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    body_len = length * body_frac
    body_start = (length - body_len) / 2
    bs_x = x1 + ux * body_start
    bs_y = y1 + uy * body_start
    be_x = x1 + ux * (body_start + body_len)
    be_y = y1 + uy * (body_start + body_len)

    # Body rectangle is rotated to align with the lead.
    angle = math.degrees(math.atan2(dy, dx))
    body_w_px = body_w_in * s
    cx = (bs_x + be_x) / 2
    cy = (bs_y + be_y) / 2
    return [
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{lead_color}" stroke-width="1.4"/>',
        f'<g transform="translate({cx:.1f},{cy:.1f}) rotate({angle:.1f})">'
        f'<rect x="{-body_len/2:.1f}" y="{-body_w_px/2:.1f}" width="{body_len:.1f}" '
        f'height="{body_w_px:.1f}" fill="{body_color}" stroke="{border_color}" stroke-width="0.8"/>'
        f'</g>',
    ]


def _render_resistor(c: Resistor, s: float) -> str:
    parts = ['<g class="resistor" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.1,
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_film_cap(c: RadialFilmCapacitor, s: float) -> str:
    parts = ['<g class="cap-film" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.18,
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_ceramic_cap(c: RadialCeramicDiskCapacitor, s: float) -> str:
    # Render as a small filled disk straddling the midpoint.
    import math

    parts = ['<g class="cap-ceramic" data-name="' + _esc(c.name) + '">']
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    parts.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#636363" stroke-width="1.2"/>'
    )
    r = max(8.0, math.hypot(x2 - x1, y2 - y1) * 0.32)
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="0.8"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_electrolytic(c: RadialElectrolytic, s: float) -> str:
    parts = ['<g class="electrolytic" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.3,
    )
    # Polarity tick on the negative end (second point unless inverted)
    pos_pt = (c.x2, c.y2) if not c.invert else (c.x1, c.y1)
    parts.append(
        f'<circle cx="{pos_pt[0]*s:.1f}" cy="{pos_pt[1]*s:.1f}" r="2.5" '
        f'fill="#ff8888" stroke="#aa3333" stroke-width="0.6"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_pot(c: PotentiometerPanel, s: float) -> str:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = _measure_to_inches(c.body_diameter) * s / 2
    parts = ['<g class="pot" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="1.2"/>'
    )
    for px, py in pts:
        parts.append(
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="3" '
            f'fill="{_color(c.wafer_color)}" stroke="#444" stroke-width="0.6"/>'
        )
    parts.append(
        f'<text x="{cx:.1f}" y="{cy+4:.1f}" font-size="9" text-anchor="middle" '
        f'fill="#000">{_esc(c.name)} {_esc(c.resistance)}</text>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _render_diode(c: DiodePlastic, s: float) -> str:
    parts = ['<g class="diode" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.08,
    )
    # Marker band on the cathode (point 2)
    import math
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    band_x = x1 + ux * (length * 0.7)
    band_y = y1 + uy * (length * 0.7)
    angle = math.degrees(math.atan2(dy, dx))
    parts.append(
        f'<g transform="translate({band_x:.1f},{band_y:.1f}) rotate({angle:.1f})">'
        f'<rect x="-1.5" y="-4" width="3" height="8" fill="{_color(c.marker_color)}"/></g>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_led(c: LED, s: float) -> str:
    import math

    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    r = max(_measure_to_inches(c.length) * s / 2, 6.0)
    parts = ['<g class="led" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#636363" stroke-width="1.2"/>'
    )
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" '
        f'stroke-width="1" fill-opacity="0.85"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_transistor(c: TransistorTO92, s: float) -> str:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = 0.12 * s  # TO-92 ~0.2 in across
    parts = ['<g class="transistor" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<path d="M{cx-r:.1f},{cy} A{r:.1f},{r:.1f} 0 1 1 {cx+r:.1f},{cy} L{cx-r:.1f},{cy} Z" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="1"/>'
    )
    for px, py in pts:
        parts.append(
            f'<line x1="{px*s:.1f}" y1="{py*s:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" '
            f'stroke="{_color(c.lead_color)}" stroke-width="1.2"/>'
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="2" fill="#000"/>'
        )
    parts.append(
        f'<text x="{cx:.1f}" y="{cy+3:.1f}" font-size="8" text-anchor="middle" '
        f'fill="{_color(c.label_color)}">{_esc(c.name)}</text>'
    )
    if c.value:
        parts.append(
            f'<text x="{cx:.1f}" y="{cy+r+10:.1f}" font-size="8" text-anchor="middle" '
            f'fill="#000">{_esc(c.value)}</text>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def _render_dil(c: DIL_IC, s: float) -> str:
    n_pins = int(c.pin_count.lstrip("_"))
    rows = n_pins // 2
    pin_spacing_in = _measure_to_inches(c.pin_spacing)
    row_spacing_in = _measure_to_inches(c.row_spacing)
    # Orientation DEFAULT: pins go down, two columns separated by row_spacing
    if c.orientation in ("DEFAULT", "_180"):
        body_w = row_spacing_in * s
        body_h = (rows - 1) * pin_spacing_in * s + 0.1 * s
        body_x = c.x * s - body_w * 0.05  # tuck slightly behind pin 1
        body_y = c.y * s - 0.05 * s
    else:  # _90 / _270 = rotated, body horizontal
        body_w = (rows - 1) * pin_spacing_in * s + 0.1 * s
        body_h = row_spacing_in * s
        body_x = c.x * s - 0.05 * s
        body_y = c.y * s - body_h * 0.05
    parts = ['<g class="dil" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<rect x="{body_x:.1f}" y="{body_y:.1f}" width="{body_w:.1f}" height="{body_h:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="1" rx="2"/>'
    )
    # Pin 1 indent
    parts.append(
        f'<circle cx="{body_x + 6:.1f}" cy="{body_y + 6:.1f}" r="2" '
        f'fill="{_color(c.indent_color)}"/>'
    )
    # Pin dots
    if c.orientation in ("DEFAULT", "_180"):
        for i in range(rows):
            y = c.y * s + i * pin_spacing_in * s
            parts.append(
                f'<circle cx="{c.x*s:.1f}" cy="{y:.1f}" r="2" fill="#000"/>'
                f'<circle cx="{c.x*s + row_spacing_in*s:.1f}" cy="{y:.1f}" r="2" fill="#000"/>'
            )
    parts.append(
        f'<text x="{body_x + body_w/2:.1f}" y="{body_y + body_h/2 + 3:.1f}" '
        f'font-size="9" text-anchor="middle" fill="{_color(c.label_color)}">'
        f'{_esc(c.value or c.name)}</text>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _render_trace(c: CopperTrace, s: float) -> str:
    pts = list(c.points)
    if len(pts) < 2:
        return ""
    d = " ".join(f"{x*s:.1f},{y*s:.1f}" for x, y in pts)
    thickness_px = max(2.0, _measure_to_inches(c.thickness) * s)
    return (
        f'<g class="trace" data-name="{_esc(c.name)}">'
        f'<polyline points="{d}" fill="none" '
        f'stroke="{_color(c.lead_color)}" stroke-width="{thickness_px:.1f}" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/></g>'
    )


def _render_jumper(c: Jumper, s: float) -> str:
    return (
        f'<g class="jumper" data-name="{_esc(c.name)}">'
        f'<line x1="{c.x1*s:.1f}" y1="{c.y1*s:.1f}" x2="{c.x2*s:.1f}" y2="{c.y2*s:.1f}" '
        f'stroke="{_color(c.color)}" stroke-width="1.6" '
        f'{"stroke-dasharray=\"5,3\"" if c.style == "DASHED" else ""}'
        f'{"stroke-dasharray=\"1,3\"" if c.style == "DOTTED" else ""}/></g>'
    )


def _render_hookup_wire(c: HookupWire, s: float) -> str:
    pts = list(c.points)
    if len(pts) == 2:
        x1, y1 = pts[0]
        x2, y2 = pts[1]
        return (
            f'<g class="wire" data-name="{_esc(c.name)}">'
            f'<line x1="{x1*s:.1f}" y1="{y1*s:.1f}" x2="{x2*s:.1f}" y2="{y2*s:.1f}" '
            f'stroke="{_color(c.color)}" stroke-width="1.8" '
            f'stroke-linecap="round"/></g>'
        )
    # Quadratic-ish smooth curve through 4 control points
    p0, p1, p2, p3 = pts
    d = (
        f"M {p0[0]*s:.1f},{p0[1]*s:.1f} "
        f"C {p1[0]*s:.1f},{p1[1]*s:.1f} "
        f"{p2[0]*s:.1f},{p2[1]*s:.1f} "
        f"{p3[0]*s:.1f},{p3[1]*s:.1f}"
    )
    return (
        f'<g class="wire" data-name="{_esc(c.name)}">'
        f'<path d="{d}" fill="none" stroke="{_color(c.color)}" '
        f'stroke-width="1.8" stroke-linecap="round"/></g>'
    )


def _render_solder_pad(c: SolderPad, s: float) -> str:
    r = _measure_to_inches(c.size) * s / 2
    hole_r = _measure_to_inches(c.hole_size) * s / 2
    return (
        f'<g class="pad" data-name="{_esc(c.name)}">'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.color)}"/>'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{hole_r:.1f}" fill="#ffffff"/>'
        f"</g>"
    )


def _render_trace_cut(c: TraceCut, s: float) -> str:
    size_px = _measure_to_inches(c.size) * s
    return (
        f'<g class="trace-cut" data-name="{_esc(c.name)}">'
        f'<rect x="{c.x*s - size_px/2:.1f}" y="{c.y*s - size_px/2:.1f}" '
        f'width="{size_px:.1f}" height="{size_px:.1f}" '
        f'fill="{_color(c.fill_color)}" stroke="{_color(c.border_color)}" '
        f'stroke-width="1"/>'
        f'<text x="{c.x*s + size_px/2 + 2:.1f}" y="{c.y*s + 3:.1f}" '
        f'font-size="7" fill="#888">cut</text>'
        f"</g>"
    )


def _render_mini_toggle(c: MiniToggleSwitch, s: float) -> str:
    pts = c._control_points()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 0.1
    box_x = (min(xs) - pad) * s
    box_y = (min(ys) - pad) * s
    box_w = (max(xs) - min(xs) + 2 * pad) * s
    box_h = (max(ys) - min(ys) + 2 * pad) * s
    parts = ['<g class="switch" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<rect x="{box_x:.1f}" y="{box_y:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" '
        f'stroke-width="1" rx="3" fill-opacity="0.7"/>'
    )
    for px, py in pts:
        parts.append(
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="3" '
            f'fill="#dddddd" stroke="#333" stroke-width="0.8"/>'
        )
    label = c.switch_type.lstrip("_")
    parts.append(
        f'<text x="{box_x + box_w/2:.1f}" y="{box_y - 4:.1f}" font-size="9" '
        f'text-anchor="middle" fill="#000">{_esc(c.name)} {_esc(label)}</text>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _render_dc_jack(c: PlasticDCJack, s: float) -> str:
    cx, cy = c.x * s + 6, c.y * s + 10
    return (
        f'<g class="dc-jack" data-name="{_esc(c.name)}">'
        f'<rect x="{c.x*s - 4:.1f}" y="{c.y*s - 4:.1f}" width="24" height="28" '
        f'fill="#202020" stroke="#000" stroke-width="1" rx="2"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="#444" stroke="#000" stroke-width="0.8"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2" fill="#000"/>'
        f'<text x="{c.x*s + 8:.1f}" y="{c.y*s + 30:.1f}" font-size="8" fill="#000">'
        f'{_esc(c.name)} 9V</text>'
        f"</g>"
    )


def _render_open_jack(c: OpenJack1_4, s: float) -> str:
    cx, cy = c.x * s, c.y * s + 10
    return (
        f'<g class="audio-jack" data-name="{_esc(c.name)}">'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="14" fill="#cccccc" stroke="#444" stroke-width="1"/>'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="#222" stroke="#000" stroke-width="0.6"/>'
        f'<text x="{cx:.1f}" y="{cy + 24:.1f}" font-size="8" text-anchor="middle" fill="#000">'
        f'{_esc(c.name)} 1/4"</text>'
        f"</g>"
    )


def _render_dot(c: Dot, s: float) -> str:
    r = _measure_to_inches(c.size) * s / 2
    return (
        f'<g class="dot" data-name="{_esc(c.name)}">'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{max(2.0, r):.1f}" '
        f'fill="{_color(c.color)}"/></g>'
    )


def _render_eyelet(c: Eyelet, s: float) -> str:
    r = _measure_to_inches(c.size) * s / 2
    hole_r = _measure_to_inches(c.hole_size) * s / 2
    return (
        f'<g class="eyelet" data-name="{_esc(c.name)}">'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.color)}" stroke="#444" stroke-width="0.6"/>'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{hole_r:.1f}" fill="#ffffff"/>'
        f"</g>"
    )


def _render_turret(c: Turret, s: float) -> str:
    r = _measure_to_inches(c.size) * s / 2
    hole_r = _measure_to_inches(c.hole_size) * s / 2
    return (
        f'<g class="turret" data-name="{_esc(c.name)}">'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.color)}" stroke="#604000" stroke-width="0.6"/>'
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="{hole_r:.1f}" fill="#000"/>'
        f"</g>"
    )


def _render_line(c: Line, s: float) -> str:
    pts = list(c.points)
    if len(pts) < 2:
        return ""
    d = " ".join(f"{x*s:.1f},{y*s:.1f}" for x, y in pts)
    return (
        f'<g class="line" data-name="{_esc(c.name)}">'
        f'<polyline points="{d}" fill="none" '
        f'stroke="{_color(c.lead_color)}" stroke-width="1.2"/></g>'
    )


def _render_axial_film_cap(c: AxialFilmCapacitor, s: float) -> str:
    parts = ['<g class="cap-axial-film" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.22,
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_axial_electrolytic(c: AxialElectrolyticCapacitor, s: float) -> str:
    parts = ['<g class="cap-axial-electro" data-name="' + _esc(c.name) + '">']
    parts += _two_pin_lead(
        (c.x1, c.y1), (c.x2, c.y2), s,
        body_color=_color(c.body_color), border_color=_color(c.border_color),
        body_w_in=0.22,
    )
    pos = (c.x2, c.y2) if not c.invert else (c.x1, c.y1)
    parts.append(
        f'<circle cx="{pos[0]*s:.1f}" cy="{pos[1]*s:.1f}" r="2.5" '
        f'fill="{_color(c.marker_color)}" stroke="#444" stroke-width="0.6"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_tube_socket(c: TubeSocket, s: float) -> str:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = _measure_to_inches(c.pin_circle_diameter) * s / 2 + 8
    parts = ['<g class="tube-socket" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
        f'fill="{_color(c.color)}" stroke="{_color(c.label_color)}" stroke-width="1"/>'
    )
    for px, py in pts:
        parts.append(
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="2.5" '
            f'fill="#222" stroke="#000" stroke-width="0.4"/>'
        )
    label = c.tube_type or c.name
    parts.append(
        f'<text x="{cx:.1f}" y="{cy+4:.1f}" font-size="10" text-anchor="middle" '
        f'fill="#000" font-weight="bold">{_esc(label)}</text>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _render_rectangle(c: Rectangle, s: float) -> str:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    rx = _measure_to_inches(c.edge_radius) * s
    return (
        f'<g class="rectangle" data-name="{_esc(c.name)}">'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'rx="{rx:.1f}" fill="{_color(c.color)}" stroke="{_color(c.border_color)}" '
        f'stroke-width="1.2" fill-opacity="0.3"/>'
        f"</g>"
    )


def _render_ellipse(c: Ellipse, s: float) -> str:
    cx = (c.x1 + c.x2) / 2 * s
    cy = (c.y1 + c.y2) / 2 * s
    rx = abs(c.x2 - c.x1) / 2 * s
    ry = abs(c.y2 - c.y1) / 2 * s
    return (
        f'<g class="ellipse" data-name="{_esc(c.name)}">'
        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
        f'fill="{_color(c.color)}" stroke="{_color(c.border_color)}" '
        f'stroke-width="1.2" fill-opacity="0.3"/>'
        f"</g>"
    )


def _render_resistor_symbol(c: ResistorSymbol, s: float) -> str:
    """Schematic resistor: a zigzag between the two endpoints."""
    import math

    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux  # perpendicular
    amp = 5.0
    parts = ['<g class="resistor-symbol" data-name="' + _esc(c.name) + '">']
    # Zigzag with 6 segments inside the middle 60% of the lead
    start_t = 0.2
    end_t = 0.8
    n_zigs = 6
    pts: list[str] = [f"{x1:.1f},{y1:.1f}"]
    sx = x1 + ux * length * start_t
    sy = y1 + uy * length * start_t
    pts.append(f"{sx:.1f},{sy:.1f}")
    for i in range(n_zigs):
        t = start_t + (end_t - start_t) * (i + 1) / (n_zigs + 1)
        side = 1 if i % 2 == 0 else -1
        px = x1 + ux * length * t + nx * amp * side
        py = y1 + uy * length * t + ny * amp * side
        pts.append(f"{px:.1f},{py:.1f}")
    ex = x1 + ux * length * end_t
    ey = y1 + uy * length * end_t
    pts.append(f"{ex:.1f},{ey:.1f}")
    pts.append(f"{x2:.1f},{y2:.1f}")
    parts.append(
        f'<polyline points="{" ".join(pts)}" fill="none" '
        f'stroke="{_color(c.border_color)}" stroke-width="1.5"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_capacitor_symbol(c: CapacitorSymbol, s: float) -> str:
    """Schematic capacitor: two parallel plates perpendicular to the lead."""
    import math

    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    half_plate = 7.0
    gap = 4.0
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    p1x = cx - ux * gap / 2
    p1y = cy - uy * gap / 2
    p2x = cx + ux * gap / 2
    p2y = cy + uy * gap / 2
    parts = ['<g class="capacitor-symbol" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{p1x:.1f}" y2="{p1y:.1f}" '
        f'stroke="{_color(c.lead_color)}" stroke-width="1.2"/>'
        f'<line x1="{p2x:.1f}" y1="{p2y:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{_color(c.lead_color)}" stroke-width="1.2"/>'
    )
    # Plates
    parts.append(
        f'<line x1="{p1x - nx*half_plate:.1f}" y1="{p1y - ny*half_plate:.1f}" '
        f'x2="{p1x + nx*half_plate:.1f}" y2="{p1y + ny*half_plate:.1f}" '
        f'stroke="{_color(c.border_color)}" stroke-width="2"/>'
        f'<line x1="{p2x - nx*half_plate:.1f}" y1="{p2y - ny*half_plate:.1f}" '
        f'x2="{p2x + nx*half_plate:.1f}" y2="{p2y + ny*half_plate:.1f}" '
        f'stroke="{_color(c.border_color)}" stroke-width="2"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_diode_symbol(c: DiodeSymbol, s: float) -> str:
    """Schematic diode: triangle pointing to cathode + perpendicular bar."""
    import math

    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    tri_back = 6
    tri_w = 5
    bar_offset = 0
    a = (cx - ux * tri_back, cy - uy * tri_back)
    b1 = (cx + nx * tri_w, cy + ny * tri_w)
    b2 = (cx - nx * tri_w, cy - ny * tri_w)
    bar_a = (cx + nx * tri_w + ux * bar_offset, cy + ny * tri_w + uy * bar_offset)
    bar_b = (cx - nx * tri_w + ux * bar_offset, cy - ny * tri_w + uy * bar_offset)
    color = _color(c.body_color)
    parts = ['<g class="diode-symbol" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{_color(c.lead_color)}" stroke-width="1.2"/>'
    )
    parts.append(
        f'<polygon points="{a[0]:.1f},{a[1]:.1f} {b1[0]:.1f},{b1[1]:.1f} '
        f'{b2[0]:.1f},{b2[1]:.1f}" fill="{color}" stroke="{color}"/>'
    )
    parts.append(
        f'<line x1="{bar_a[0]:.1f}" y1="{bar_a[1]:.1f}" '
        f'x2="{bar_b[0]:.1f}" y2="{bar_b[1]:.1f}" stroke="{color}" stroke-width="2"/>'
    )
    parts.append(_value_label(c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display))
    parts.append("</g>")
    return "\n".join(parts)


def _render_bjt_symbol(c: BJTSymbol, s: float) -> str:
    pts = c._control_points()
    base, col, emi, _lbl = pts
    bx, by = base[0] * s, base[1] * s
    cx, cy = col[0] * s, col[1] * s
    ex, ey = emi[0] * s, emi[1] * s
    # Junction circle
    jx, jy = (bx + cx + ex) / 3, (by + cy + ey) / 3
    color = _color(c.color)
    parts = ['<g class="bjt-symbol" data-name="' + _esc(c.name) + '">']
    parts.append(
        f'<circle cx="{jx:.1f}" cy="{jy:.1f}" r="12" fill="none" '
        f'stroke="{color}" stroke-width="1.2"/>'
    )
    for pt in [(cx, cy), (ex, ey)]:
        parts.append(
            f'<line x1="{pt[0]:.1f}" y1="{pt[1]:.1f}" x2="{jx:.1f}" y2="{jy:.1f}" '
            f'stroke="{color}" stroke-width="1.2"/>'
        )
    parts.append(
        f'<line x1="{bx:.1f}" y1="{by:.1f}" x2="{jx - 6:.1f}" y2="{jy:.1f}" '
        f'stroke="{color}" stroke-width="1.2"/>'
    )
    # Polarity arrow on the emitter
    arrow_tip = (ex, ey) if c.polarity == "NPN" else (jx, jy)
    parts.append(
        f'<circle cx="{arrow_tip[0]:.1f}" cy="{arrow_tip[1]:.1f}" r="2.5" '
        f'fill="{color}"/>'
    )
    label = c.value or c.name
    parts.append(
        f'<text x="{jx + 14:.1f}" y="{jy + 4:.1f}" font-size="9" fill="#000">'
        f'{_esc(label)} {_esc(c.polarity)}</text>'
    )
    parts.append("</g>")
    return "\n".join(parts)


def _render_ground_symbol(c: GroundSymbol, s: float) -> str:
    x, y = c.x * s, c.y * s
    size_px = _measure_to_inches(c.size) * s
    color = _color(c.color)
    if c.type == "TRIANGLE":
        return (
            f'<g class="ground" data-name="{_esc(c.name)}">'
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y+size_px*0.4:.1f}" '
            f'stroke="{color}" stroke-width="1.2"/>'
            f'<polygon points="{x-size_px*0.5:.1f},{y+size_px*0.4:.1f} '
            f'{x+size_px*0.5:.1f},{y+size_px*0.4:.1f} '
            f'{x:.1f},{y+size_px:.1f}" fill="{color}"/></g>'
        )
    return (
        f'<g class="ground" data-name="{_esc(c.name)}">'
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y+size_px*0.4:.1f}" '
        f'stroke="{color}" stroke-width="1.2"/>'
        f'<line x1="{x-size_px*0.5:.1f}" y1="{y+size_px*0.4:.1f}" '
        f'x2="{x+size_px*0.5:.1f}" y2="{y+size_px*0.4:.1f}" '
        f'stroke="{color}" stroke-width="1.5"/>'
        f'<line x1="{x-size_px*0.3:.1f}" y1="{y+size_px*0.6:.1f}" '
        f'x2="{x+size_px*0.3:.1f}" y2="{y+size_px*0.6:.1f}" '
        f'stroke="{color}" stroke-width="1.5"/>'
        f'<line x1="{x-size_px*0.15:.1f}" y1="{y+size_px*0.8:.1f}" '
        f'x2="{x+size_px*0.15:.1f}" y2="{y+size_px*0.8:.1f}" '
        f'stroke="{color}" stroke-width="1.5"/>'
        f"</g>"
    )


def _render_curved_trace(c: CurvedTrace, s: float) -> str:
    pts = list(c.points)
    if len(pts) == 2:
        x1, y1 = pts[0]
        x2, y2 = pts[1]
        return (
            f'<g class="curved-trace" data-name="{_esc(c.name)}">'
            f'<line x1="{x1*s:.1f}" y1="{y1*s:.1f}" x2="{x2*s:.1f}" y2="{y2*s:.1f}" '
            f'stroke="{_color(c.color)}" stroke-width="2" stroke-linecap="round"/></g>'
        )
    p0, p1, p2, p3 = pts
    thickness_px = max(2.0, _measure_to_inches(c.size) * s)
    d = (
        f"M {p0[0]*s:.1f},{p0[1]*s:.1f} "
        f"C {p1[0]*s:.1f},{p1[1]*s:.1f} "
        f"{p2[0]*s:.1f},{p2[1]*s:.1f} "
        f"{p3[0]*s:.1f},{p3[1]*s:.1f}"
    )
    return (
        f'<g class="curved-trace" data-name="{_esc(c.name)}">'
        f'<path d="{d}" fill="none" stroke="{_color(c.color)}" '
        f'stroke-width="{thickness_px:.1f}" stroke-linecap="round"/></g>'
    )


def _render_trimmer(c: TrimmerPotentiometer, s: float) -> str:
    pts = c._control_points()
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    cx = (min(xs) + max(xs)) / 2 * s
    cy = (min(ys) + max(ys)) / 2 * s
    size = 14
    out = ['<g class="trimmer" data-name="' + _esc(c.name) + '">']
    out.append(
        f'<rect x="{cx - size:.1f}" y="{cy - size:.1f}" width="{2*size}" height="{2*size}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="1" rx="2"/>'
    )
    for px, py in pts:
        out.append(
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="2" fill="#222"/>'
        )
    out.append(
        f'<text x="{cx:.1f}" y="{cy+3:.1f}" font-size="8" text-anchor="middle" '
        f'fill="#000">{_esc(c.name)} {_esc(c.resistance)}</text>'
    )
    out.append("</g>")
    return "\n".join(out)


def _render_terminal_strip(c: TerminalStrip, s: float) -> str:
    pts = c._control_points()
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    pad = 0.08
    x = (min(xs) - pad) * s
    y = (min(ys) - pad) * s
    w = (max(xs) - min(xs) + 2 * pad) * s
    h = (max(ys) - min(ys) + 2 * pad) * s
    out = ['<g class="terminal-strip" data-name="' + _esc(c.name) + '">']
    out.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{_color(c.body_color)}" stroke="{_color(c.border_color)}" stroke-width="1" rx="2"/>'
    )
    for px, py in pts:
        out.append(
            f'<circle cx="{px*s:.1f}" cy="{py*s:.1f}" r="2.5" '
            f'fill="#333" stroke="#000" stroke-width="0.4"/>'
        )
    out.append("</g>")
    return "\n".join(out)


def _render_image_placeholder(c: Image, s: float) -> str:
    # Show a hatched rectangle where the image lives — we don't decode the
    # base64 here, this is a preview only.
    x, y = c.x * s, c.y * s
    return (
        f'<g class="image" data-name="{_esc(c.name)}">'
        f'<rect x="{x-30:.1f}" y="{y-30:.1f}" width="60" height="60" '
        f'fill="#ffffff" stroke="#888" stroke-dasharray="4,3"/>'
        f'<text x="{x:.1f}" y="{y+4:.1f}" font-size="9" text-anchor="middle" '
        f'fill="#888">[image]</text></g>'
    )


def _render_bom(c: BOM, s: float) -> str:
    x, y = c.x * s, c.y * s
    size_px = _measure_to_inches(c.size) * s
    return (
        f'<g class="bom" data-name="{_esc(c.name)}">'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{size_px:.1f}" height="{size_px:.1f}" '
        f'fill="#ffffff" stroke="{_color(c.color)}" stroke-dasharray="3,2"/>'
        f'<text x="{x + size_px/2:.1f}" y="{y + size_px/2 + 4:.1f}" '
        f'font-size="10" text-anchor="middle" fill="{_color(c.color)}">BOM</text></g>'
    )


def _render_label(c: Label, s: float) -> str:
    style = ""
    if c.font_style in (1, 3):
        style += "font-weight:bold;"
    if c.font_style in (2, 3):
        style += "font-style:italic;"
    anchor = {"LEFT": "start", "CENTER": "middle", "RIGHT": "end"}.get(
        c.horizontal_alignment, "middle"
    )
    return (
        f'<g class="label" data-name="{_esc(c.name)}">'
        f'<text x="{c.x*s:.1f}" y="{c.y*s:.1f}" '
        f'font-size="{c.font_size}" text-anchor="{anchor}" '
        f'fill="{_color(c.color)}" style="{style}">{_esc(c.text)}</text>'
        f"</g>"
    )


def _value_label(x1: float, y1: float, x2: float, y2: float, s: float,
                 name: str, value: str, display: str) -> str:
    cx = (x1 + x2) / 2 * s
    cy = (y1 + y2) / 2 * s - 7
    if display == "NONE":
        return ""
    if display == "NAME":
        text = name
    elif display == "VALUE":
        text = value or name
    elif display == "BOTH":
        text = f"{name} {value}" if value else name
    else:
        text = value or name
    return (
        f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="8" text-anchor="middle" '
        f'fill="#000">{_esc(text)}</text>'
    )


def _render_ground_fill(c: GroundFill, s: float) -> str:
    if len(c.points) < 3:
        return ""
    pts = " ".join(f"{x*s:.1f},{y*s:.1f}" for x, y in c.points)
    return (
        f'<polygon points="{pts}" fill="#{c.color}" fill-opacity="0.35" '
        f'stroke="#{c.color}" stroke-width="1"/>'
    )


def _render_elliptical_cutout(c: EllipticalCutout, s: float) -> str:
    cx = (c.x1 + c.x2) / 2 * s
    cy = (c.y1 + c.y2) / 2 * s
    rx = abs(c.x2 - c.x1) / 2 * s
    ry = abs(c.y2 - c.y1) / 2 * s
    if rx <= 0 or ry <= 0:
        return ""
    fa = c.alpha / 255
    return (
        f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
        f'fill="#{c.color}" fill-opacity="{fa:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_pin_header(c: PinHeader, s: float) -> str:
    out = []
    for x, y in c.points:
        out.append(
            f'<circle cx="{x*s:.1f}" cy="{y*s:.1f}" r="3.5" '
            f'fill="#333" stroke="#000" stroke-width="0.8"/>'
        )
    return "<g>" + "".join(out) + "</g>"


def _render_polygon(c: Polygon, s: float) -> str:
    if len(c.points) < 3:
        return ""
    pts = " ".join(f"{x*s:.1f},{y*s:.1f}" for x, y in c.points)
    fa = c.alpha / 255
    return (
        f'<polygon points="{pts}" fill="#{c.color}" fill-opacity="{fa:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_wrap_label(c: WrapLabel, s: float) -> str:
    # SVG has no native wrapping; render at the top-left anchor as a single
    # line. DIYLC's own wrap layout would need text-extent math we don't have.
    x = c.x1 * s
    y = c.y1 * s + c.font_size
    anchor = {"LEFT": "start", "CENTER": "middle", "RIGHT": "end"}.get(
        c.horizontal_alignment, "start"
    )
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{c.font_size}" '
        f'text-anchor="{anchor}" fill="#{c.color}">{_esc(c.text)}</text>'
    )


def _render_diode_glass(c: DiodeGlass, s: float) -> str:
    # Same geometry as DiodePlastic but with the glass body-color default.
    # Reuse the DiodePlastic renderer to stay consistent.
    return _render_diode_like(c, s, body_color=c.body_color)


def _render_diode_like(c, s: float, *, body_color: str) -> str:
    import math
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    body_len = max(L * 0.5, 14)
    body_w = 8
    px, py = -uy, ux
    hl = body_len / 2
    hw = body_w / 2
    corners = [
        (cx - ux*hl + px*hw, cy - uy*hl + py*hw),
        (cx + ux*hl + px*hw, cy + uy*hl + py*hw),
        (cx + ux*hl - px*hw, cy + uy*hl - py*hw),
        (cx - ux*hl - px*hw, cy - uy*hl - py*hw),
    ]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
    fa = c.alpha / 255
    leads = (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{cx-ux*hl:.1f}" y2="{cy-uy*hl:.1f}" '
        f'stroke="#{c.lead_color}" stroke-width="1.2"/>'
        f'<line x1="{cx+ux*hl:.1f}" y1="{cy+uy*hl:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#{c.lead_color}" stroke-width="1.2"/>'
    )
    body = (
        f'<polygon points="{pts}" fill="#{body_color}" fill-opacity="{fa:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )
    return "<g>" + leads + body + "</g>"


def _render_pcb_text(c: PCBText, s: float) -> str:
    return (
        f'<text x="{c.x*s:.1f}" y="{c.y*s + c.font_size:.1f}" '
        f'font-family="monospace" font-size="{c.font_size}" '
        f'fill="#{c.color}">{_esc(c.text)}</text>'
    )


def _render_potentiometer_symbol(c: PotentiometerSymbol, s: float) -> str:
    pts = c._control_points()
    sx = [p[0] * s for p in pts]
    sy = [p[1] * s for p in pts]
    cx, cy = sum(sx) / 3, sum(sy) / 3
    lines = "".join(
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
        f'stroke="#{c.color}" stroke-width="1"/>'
        for x, y in zip(sx, sy)
    )
    body = (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" '
        f'fill="none" stroke="#{c.color}" stroke-width="1"/>'
    )
    return "<g>" + lines + body + "</g>"


def _render_closed_jack(c: ClosedJack1_4, s: float) -> str:
    x, y = c.x * s, c.y * s
    fa = c.alpha / 255
    return (
        f'<rect x="{x-4:.1f}" y="{y-4:.1f}" width="{0.3*s:.1f}" height="{0.8*s:.1f}" '
        f'fill="#666" fill-opacity="{fa:.2f}" stroke="#000" stroke-width="1"/>'
    )


def _render_rca_jack(c: RCAJack, s: float) -> str:
    x, y = c.x * s, c.y * s
    fa = c.alpha / 255
    return (
        f'<g>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.12*s:.1f}" '
        f'fill="#b39855" fill-opacity="{fa:.2f}" stroke="#000" stroke-width="1"/>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.04*s:.1f}" fill="#000"/>'
        f'</g>'
    )


def _render_transformer_coil(c: TransformerCoil, s: float) -> str:
    import math
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    bumps = max(3, int(L / 8))
    path_parts = [f"M {x1:.1f},{y1:.1f}"]
    for i in range(bumps):
        t = (i + 1) / bumps
        bx = x1 + dx * t
        by = y1 + dy * t
        r = L / (bumps * 2)
        # Sweep flag alternates so the bumps stay on the same side.
        path_parts.append(f"A {r:.1f},{r:.1f} 0 0 1 {bx:.1f},{by:.1f}")
    d = " ".join(path_parts)
    return (
        f'<path d="{d}" fill="none" stroke="#{c.color}" stroke-width="1.2"/>'
    )


def _render_transformer_core(c: TransformerCore, s: float) -> str:
    return (
        f'<line x1="{c.x1*s:.1f}" y1="{c.y1*s:.1f}" '
        f'x2="{c.x2*s:.1f}" y2="{c.y2*s:.1f}" '
        f'stroke="#{c.color}" stroke-width="2"/>'
    )


def _render_triode_symbol(c: TriodeSymbol, s: float) -> str:
    x, y = c.x * s, c.y * s
    r = 0.3 * s
    return (
        f'<g>'
        f'<circle cx="{x+r:.1f}" cy="{y:.1f}" r="{r:.1f}" '
        f'fill="none" stroke="#{c.color}" stroke-width="1.2"/>'
        f'<line x1="{x+r-6:.1f}" y1="{y-r:.1f}" x2="{x+r+6:.1f}" y2="{y-r:.1f}" '
        f'stroke="#{c.color}" stroke-width="1.2"/>'
        f'</g>'
    )


def _render_single_coil_pickup(c: SingleCoilPickup, s: float) -> str:
    x, y = c.x * s, c.y * s
    w, h = 0.7 * s, 1.0 * s
    fa = c.alpha / 255
    poles = "".join(
        f'<circle cx="{x:.1f}" cy="{y - h/2 + (i+0.5)*(h/6):.1f}" r="2.5" fill="#888"/>'
        for i in range(6)
    )
    return (
        f'<g>'
        f'<rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="#{c.color}" fill-opacity="{fa:.2f}" '
        f'stroke="#{c.base_color}" stroke-width="1.2"/>'
        f'{poles}'
        f'</g>'
    )


def _render_cliff_jack(c: CliffJack1_4, s: float) -> str:
    x = c.x * s
    y = c.y * s
    w = 0.4 * s
    h = 0.3 * s
    fa = c.alpha / 255
    return (
        f'<rect x="{x-4:.1f}" y="{y-4:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="#{c.body_color}" fill-opacity="{fa:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_tag_strip(c: TagStrip, s: float) -> str:
    ts = c.terminal_spacing.to_inches()
    h = (c.terminal_count - 1) * ts + 0.2
    body = (
        f'<rect x="{(c.x-0.05)*s:.1f}" y="{(c.y-0.1)*s:.1f}" '
        f'width="{0.3*s:.1f}" height="{h*s:.1f}" '
        f'fill="#{c.board_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#3d1f00" stroke-width="1"/>'
    )
    lugs = "".join(
        f'<circle cx="{c.x*s:.1f}" cy="{(c.y+i*ts)*s:.1f}" r="3" fill="#666" stroke="#000"/>'
        for i in range(c.terminal_count)
    )
    return "<g>" + body + lugs + "</g>"


def _render_pilot_lamp(c: PilotLampHolder, s: float) -> str:
    return (
        f'<circle cx="{c.x*s:.1f}" cy="{c.y*s:.1f}" r="12" '
        f'fill="#ffd84d" fill-opacity="{c.alpha/255:.2f}" stroke="#4c3200" stroke-width="1"/>'
    )


def _render_multi_section_cap(c: MultiSectionCapacitor, s: float) -> str:
    sections = len(c.values)
    h = sections * 0.2 + 0.1
    return (
        f'<rect x="{(c.x-0.15)*s:.1f}" y="{(c.y-0.1)*s:.1f}" '
        f'width="{0.3*s:.1f}" height="{h*s:.1f}" '
        f'fill="#{c.body_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_tape_measure(c: TapeMeasure, s: float) -> str:
    return (
        f'<line x1="{c.x1*s:.1f}" y1="{c.y1*s:.1f}" '
        f'x2="{c.x2*s:.1f}" y2="{c.y2*s:.1f}" '
        f'stroke="#{c.color}" stroke-width="1" '
        f'marker-start="url(#arrow)" marker-end="url(#arrow)"/>'
    )


def _render_fuse_holder(c: FuseHolderPanel, s: float) -> str:
    return (
        f'<rect x="{(c.x-0.05)*s:.1f}" y="{c.y*s:.1f}" '
        f'width="{0.1*s:.1f}" height="{0.2*s:.1f}" '
        f'fill="#{c.body_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_audio_transformer(c: AudioTransformer, s: float) -> str:
    w = c.coil_width.to_inches() * s
    h = c.coil_length.to_inches() * s
    return (
        f'<rect x="{c.x*s - w/2:.1f}" y="{c.y*s:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'fill="#{c.coil_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.core_color}" stroke-width="1.5"/>'
    )


def _render_led_symbol(c: LEDSymbol, s: float) -> str:
    import math
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    size = 8
    p1 = (cx - ux * size, cy - uy * size)
    p2 = (cx + ux * size, cy + uy * size)
    p3 = (cx + px * size, cy + py * size)
    pts = f"{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}"
    return (
        f'<polygon points="{pts}" fill="#{c.body_color}" '
        f'stroke="#000" stroke-width="1"/>'
    )


def _render_sil_ic(c: SIL_IC, s: float) -> str:
    n = int(c.pin_count.lstrip("_"))
    ps = c.pin_spacing.to_inches()
    w = (n - 1) * ps + 0.1
    return (
        f'<rect x="{(c.x-0.05)*s:.1f}" y="{(c.y-0.1)*s:.1f}" '
        f'width="{w*s:.1f}" height="{0.25*s:.1f}" '
        f'fill="#{c.body_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


def _render_chassis_panel(c: ChassisPanel, s: float) -> str:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="#{c.color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1.5"/>'
    )


def _render_transistor_to1(c: TransistorTO1, s: float) -> str:
    cy = (c.y + c.pin_spacing.to_inches()) * s
    return (
        f'<circle cx="{c.x*s:.1f}" cy="{cy:.1f}" r="{0.18*s:.1f}" '
        f'fill="#{c.body_color}" fill-opacity="{c.alpha/255:.2f}" '
        f'stroke="#{c.border_color}" stroke-width="1"/>'
    )


_RENDERERS: dict[type, callable] = {
    BlankBoard: _render_blank_board,
    PerfBoard: _render_perf_board,
    VeroBoard: _render_vero_board,
    Resistor: _render_resistor,
    RadialFilmCapacitor: _render_film_cap,
    RadialCeramicDiskCapacitor: _render_ceramic_cap,
    RadialElectrolytic: _render_electrolytic,
    AxialFilmCapacitor: _render_axial_film_cap,
    AxialElectrolyticCapacitor: _render_axial_electrolytic,
    PotentiometerPanel: _render_pot,
    TrimmerPotentiometer: _render_trimmer,
    TerminalStrip: _render_terminal_strip,
    Image: _render_image_placeholder,
    BOM: _render_bom,
    ResistorSymbol: _render_resistor_symbol,
    CapacitorSymbol: _render_capacitor_symbol,
    DiodeSymbol: _render_diode_symbol,
    BJTSymbol: _render_bjt_symbol,
    GroundSymbol: _render_ground_symbol,
    CurvedTrace: _render_curved_trace,
    TubeSocket: _render_tube_socket,
    Rectangle: _render_rectangle,
    Ellipse: _render_ellipse,
    DiodePlastic: _render_diode,
    LED: _render_led,
    TransistorTO92: _render_transistor,
    DIL_IC: _render_dil,
    CopperTrace: _render_trace,
    Jumper: _render_jumper,
    HookupWire: _render_hookup_wire,
    SolderPad: _render_solder_pad,
    Dot: _render_dot,
    Eyelet: _render_eyelet,
    Turret: _render_turret,
    Line: _render_line,
    TraceCut: _render_trace_cut,
    MiniToggleSwitch: _render_mini_toggle,
    PlasticDCJack: _render_dc_jack,
    OpenJack1_4: _render_open_jack,
    Label: _render_label,
    GroundFill: _render_ground_fill,
    EllipticalCutout: _render_elliptical_cutout,
    PinHeader: _render_pin_header,
    Polygon: _render_polygon,
    WrapLabel: _render_wrap_label,
    DiodeGlass: _render_diode_glass,
    PCBText: _render_pcb_text,
    PotentiometerSymbol: _render_potentiometer_symbol,
    CliffJack1_4: _render_cliff_jack,
    ClosedJack1_4: _render_closed_jack,
    RCAJack: _render_rca_jack,
    TransformerCoil: _render_transformer_coil,
    TransformerCore: _render_transformer_core,
    TriodeSymbol: _render_triode_symbol,
    SingleCoilPickup: _render_single_coil_pickup,
    TagStrip: _render_tag_strip,
    PilotLampHolder: _render_pilot_lamp,
    MultiSectionCapacitor: _render_multi_section_cap,
    TapeMeasure: _render_tape_measure,
    FuseHolderPanel: _render_fuse_holder,
    AudioTransformer: _render_audio_transformer,
    LEDSymbol: _render_led_symbol,
    SIL_IC: _render_sil_ic,
    ChassisPanel: _render_chassis_panel,
    TransistorTO1: _render_transistor_to1,
}
