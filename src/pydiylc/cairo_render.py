"""Cairo backend for the pydiylc viewer.

Mirrors the shape choices in `pydiylc.svg` but draws directly onto a Cairo
context. Stays import-safe when Cairo is not installed — viewer code
imports lazily through ``has_cairo()`` so users without GTK can still use
the SVG path.

There is intentional duplication with ``svg.py``. Once the per-component
shapes stabilize, both backends should be refactored to share a
``Canvas`` protocol; for now the duplication is small and easy to keep
in lockstep.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .components import (
    AxialElectrolyticCapacitor,
    AxialFilmCapacitor,
    BJTSymbol,
    BlankBoard,
    BOM,
    CapacitorSymbol,
    CliffJack1_4,
    ClosedJack1_4,
    Component,
    CopperTrace,
    CurvedTrace,
    DiodeGlass,
    DiodePlastic,
    DIL_IC,
    DiodeSymbol,
    Dot,
    Ellipse,
    EllipticalCutout,
    Eyelet,
    GroundFill,
    GroundSymbol,
    HookupWire,
    Image,
    Jumper,
    Line,
    PCBText,
    PerfBoard,
    PinHeader,
    PlasticDCJack,
    Polygon,
    PotentiometerPanel,
    PotentiometerSymbol,
    Rectangle,
    ResistorSymbol,
    TerminalStrip,
    TrimmerPotentiometer,
    TubeSocket,
    Label,
    LED,
    MiniToggleSwitch,
    OpenJack1_4,
    RadialCeramicDiskCapacitor,
    RadialElectrolytic,
    RadialFilmCapacitor,
    RCAJack,
    Resistor,
    SingleCoilPickup,
    SolderPad,
    TraceCut,
    TransformerCoil,
    TransformerCore,
    TransistorTO92,
    TriodeSymbol,
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
    TransistorTO220,
    IECSocket,
    TantalumCapacitor,
    EyeletBoard,
    InductorSymbol,
    PentodeSymbol,
    Breadboard,
    LeverSwitch,
    ZenerDiodeSymbol,
    MarshallPerfBoard,
    MiniRelay,
    RectangularCutout,
    JazzBassPickup,
    PBassPickup,
    HumbuckerPickup,
    LPSwitch,
    BatterySnap9V,
    ICSymbol,
    RotarySelectorSwitch,
    BatterySymbol,
    ElectrolyticCanCapacitor,
    TriPadBoard,
    FuseSymbol,
    TubeDiodeSymbol,
    JFETSymbol,
    CrystalOscillator,
    NeutrikJack1_4,
    TransistorTO126,
    P90Pickup,
    SMDResistor,
    SMDCapacitor,
    SchottkyDiodeSymbol,
    BridgeRectifier,
    PhotoDiodeSymbol,
)
from .core import Measure, Project
from .svg import PX_PER_INCH


if TYPE_CHECKING:  # only for type hints — never imported at runtime
    import cairo  # type: ignore


def has_cairo() -> bool:
    """Return True if pycairo is importable."""
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


def render_png(project, path, *, dpi: float = PX_PER_INCH, pad_px: float = 16.0,
               background: tuple[float, float, float] = (1, 1, 1),
               show_grid: bool = True) -> None:
    """Rasterize a Project to a PNG file via pycairo.

    Requires the optional `pycairo` dependency. If it's not installed, this
    raises ImportError with a hint.
    """
    try:
        import cairo
    except ImportError as exc:
        raise ImportError(
            "PNG export requires pycairo. Install with `pip install pycairo` "
            "or `pip install pydiylc[viewer]`."
        ) from exc

    w_in = project.width_cm / 2.54
    h_in = project.height_cm / 2.54
    w = int(w_in * dpi + 2 * pad_px)
    h = int(h_in * dpi + 2 * pad_px)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.translate(pad_px, pad_px)
    draw_project(cr, project, scale=dpi, background=background, show_grid=show_grid)
    surface.write_to_png(str(path))


def _measure_to_inches(m: Measure) -> float:
    if m.unit == "in":
        return m.value
    if m.unit == "mm":
        return m.value / 25.4
    if m.unit == "cm":
        return m.value / 2.54
    if m.unit == "px":
        return m.value / PX_PER_INCH
    return m.value


def _hex_to_rgb(hex6: str) -> tuple[float, float, float]:
    s = hex6.lstrip("#").lower()
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return int(s[0:2], 16) / 255, int(s[2:4], 16) / 255, int(s[4:6], 16) / 255


def draw_project(cr, project: Project, *, scale: float = PX_PER_INCH,
                 background: tuple[float, float, float] = (1, 1, 1),
                 show_grid: bool = True,
                 selected_name: str | None = None,
                 selected_names: "set[str] | list[str] | None" = None,
                 focus_pin: tuple[float, float] | None = None) -> None:
    """Paint a Project onto an existing Cairo context.

    The caller is responsible for sizing the surface and applying any pan/zoom
    transforms before calling. ``scale`` is pixels per inch *at the current
    Cairo transform*; pass 96 for 1:1, or use Cairo's own ``cr.scale(zoom,
    zoom)`` to magnify.

    Pass ``selected_name`` to highlight one component, or
    ``selected_names`` (a set or list) to highlight several at once. If
    both are given, the set is used and ``selected_name`` is ignored.
    """
    selection_set: set[str] = set()
    if selected_names is not None:
        selection_set = set(selected_names)
    elif selected_name is not None:
        selection_set = {selected_name}
    w_in = project.width_cm / 2.54
    h_in = project.height_cm / 2.54
    w = w_in * scale
    h = h_in * scale

    # Drop shadow — subtle, gives the page some "lifted" feel against the
    # gray off-canvas backdrop.
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.18)
    cr.rectangle(4, 4, w, h)
    cr.fill()

    # Page background.
    cr.set_source_rgb(*background)
    cr.rectangle(0, 0, w, h)
    cr.fill()

    # Approximate luminance to decide grid + border tone. Below 0.5 we're
    # on a dark "sheet" and want bright-but-faint grid lines instead of
    # the default light-gray ones (which would vanish on a dark page).
    dark_page = (0.299 * background[0] + 0.587 * background[1]
                 + 0.114 * background[2]) < 0.5

    if show_grid:
        _draw_grid(cr, w_in, h_in, scale, dark_page=dark_page)

    # Crisp page border so the project bounds are unmistakable.
    if dark_page:
        cr.set_source_rgb(0.45, 0.42, 0.55)
    else:
        cr.set_source_rgb(0.55, 0.55, 0.6)
    cr.set_line_width(1.0)
    cr.rectangle(0.5, 0.5, w - 1, h - 1)
    cr.stroke()

    for component in project.components:
        try:
            handler = _RENDERERS.get(type(component))
            if handler is None:
                _draw_fallback(cr, component, scale)
            else:
                handler(cr, component, scale)
                if selection_set and getattr(component, "name", None) in selection_set:
                    _draw_selection_box(cr, component, scale)
        except Exception:
            # Don't let a bad component blank the canvas
            pass

    # Pin-level focus marker (when the tree editor has drilled into a node).
    if focus_pin is not None:
        cr.save()
        cr.set_source_rgba(1.0, 0.45, 0.0, 0.9)
        cr.set_line_width(2.0)
        cr.arc(focus_pin[0] * scale, focus_pin[1] * scale, 7, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgba(1.0, 0.45, 0.0, 0.25)
        cr.arc(focus_pin[0] * scale, focus_pin[1] * scale, 4, 0, 2 * math.pi)
        cr.fill()
        cr.restore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _draw_grid(cr, w_in: float, h_in: float, scale: float,
               step_in: float = 0.1, *, dark_page: bool = False) -> None:
    """Fine grid every ``step_in`` inches, plus emphasized lines every inch.

    The fine grid is a light gray; the inch lines are a touch darker so the
    eye picks out coordinates at a glance without rulers. On a dark page we
    flip to faintly-bright lines so they stay visible.
    """
    cr.save()
    # Fine grid (every 0.1 in).
    if dark_page:
        cr.set_source_rgb(0.30, 0.27, 0.36)
    else:
        cr.set_source_rgb(0.93, 0.93, 0.93)
    cr.set_line_width(0.5)
    n_x = int(w_in / step_in)
    n_y = int(h_in / step_in)
    for i in range(n_x + 1):
        x = i * step_in * scale
        cr.move_to(x, 0)
        cr.line_to(x, h_in * scale)
    for i in range(n_y + 1):
        y = i * step_in * scale
        cr.move_to(0, y)
        cr.line_to(w_in * scale, y)
    cr.stroke()

    # Emphasized inch lines.
    if dark_page:
        cr.set_source_rgb(0.42, 0.38, 0.50)
    else:
        cr.set_source_rgb(0.78, 0.78, 0.82)
    cr.set_line_width(0.8)
    nx_in = int(w_in)
    ny_in = int(h_in)
    for i in range(nx_in + 1):
        x = i * scale
        cr.move_to(x, 0)
        cr.line_to(x, h_in * scale)
    for i in range(ny_in + 1):
        y = i * scale
        cr.move_to(0, y)
        cr.line_to(w_in * scale, y)
    cr.stroke()

    # Inch labels along the top and left edges (small, dim).
    if dark_page:
        cr.set_source_rgb(0.70, 0.66, 0.78)
    else:
        cr.set_source_rgb(0.55, 0.55, 0.58)
    cr.set_font_size(8)
    for i in range(1, nx_in + 1):
        cr.move_to(i * scale - 6, -3)
        cr.show_text(str(i))
    for i in range(1, ny_in + 1):
        cr.move_to(-12, i * scale + 3)
        cr.show_text(str(i))
    cr.restore()


def _draw_fallback(cr, c: Component, s: float) -> None:
    x = getattr(c, "x", None)
    if x is None:
        x = getattr(c, "x1", 0.0)
    y = getattr(c, "y", None)
    if y is None:
        y = getattr(c, "y1", 0.0)
    cr.save()
    cr.set_source_rgb(0.6, 0.6, 0.6)
    cr.set_dash([2, 2])
    cr.arc(x * s, y * s, 4, 0, 2 * math.pi)
    cr.stroke()
    cr.restore()


def _draw_selection_box(cr, c: Component, s: float) -> None:
    """Draw a dashed outline around a selected component."""
    bbox = _component_bbox(c, s)
    if bbox is None:
        return
    x1, y1, x2, y2 = bbox
    pad = 4
    cr.save()
    cr.set_source_rgba(0.0, 0.4, 0.9, 0.9)
    cr.set_line_width(1.5)
    cr.set_dash([4, 3])
    cr.rectangle(x1 - pad, y1 - pad, (x2 - x1) + 2 * pad, (y2 - y1) + 2 * pad)
    cr.stroke()
    cr.restore()


def _component_bbox(c: Component, s: float) -> tuple[float, float, float, float] | None:
    """Approximate bounding box in pixel coordinates for hit testing + selection."""
    if hasattr(c, "x1") and hasattr(c, "x2"):
        return (
            min(c.x1, c.x2) * s,
            min(c.y1, c.y2) * s,
            max(c.x1, c.x2) * s,
            max(c.y1, c.y2) * s,
        )
    if hasattr(c, "points") and c.points:
        xs = [p[0] for p in c.points]
        ys = [p[1] for p in c.points]
        return (min(xs) * s, min(ys) * s, max(xs) * s, max(ys) * s)
    # Components that auto-generate control points (transistor, pot, switch)
    if hasattr(c, "_control_points"):
        pts = c._control_points()
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs) * s, min(ys) * s, max(xs) * s, max(ys) * s)
    if hasattr(c, "x") and hasattr(c, "y"):
        x, y = c.x * s, c.y * s
        return (x - 8, y - 8, x + 8, y + 8)
    return None


def hit_test(project: Project, px: float, py: float, scale: float) -> Component | None:
    """Return the topmost component whose bbox contains (px, py), or None."""
    # Iterate in reverse — later-added components are drawn on top.
    for c in reversed(project.components):
        bbox = _component_bbox(c, scale)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        pad = 6  # hit-test padding for small components
        if (x1 - pad) <= px <= (x2 + pad) and (y1 - pad) <= py <= (y2 + pad):
            return c
    return None


# ---------------------------------------------------------------------------
# Per-component renderers (mirror svg.py shapes)
# ---------------------------------------------------------------------------


def _board_rect(cr, c, s: float) -> tuple[float, float, float, float]:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    cr.set_source_rgb(*_hex_to_rgb(c.board_color))
    cr.rectangle(x, y, w, h)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    return x, y, w, h


def _render_blank_board(cr, c: BlankBoard, s: float) -> None:
    _board_rect(cr, c, s)


def _render_perf_board(cr, c: PerfBoard, s: float) -> None:
    x, y, w, h = _board_rect(cr, c, s)
    step = _measure_to_inches(c.spacing) * s
    nx = int(w / step) + 1
    ny = int(h / step) + 1
    cr.set_source_rgb(*_hex_to_rgb(c.pad_color))
    for i in range(nx):
        for j in range(ny):
            cr.arc(x + i * step, y + j * step, 1.6, 0, 2 * math.pi)
            cr.fill()


def _render_vero_board(cr, c: VeroBoard, s: float) -> None:
    x, y, w, h = _board_rect(cr, c, s)
    step = _measure_to_inches(c.spacing) * s
    cr.set_source_rgba(*_hex_to_rgb(c.strip_color), 0.55)
    cr.set_line_width(3)
    if c.orientation == "HORIZONTAL":
        ny = max(1, int(h / step))
        for i in range(ny):
            cy = y + (i + 0.5) * step
            cr.move_to(x, cy)
            cr.line_to(x + w, cy)
    else:
        nx = max(1, int(w / step))
        for i in range(nx):
            cx = x + (i + 0.5) * step
            cr.move_to(cx, y)
            cr.line_to(cx, y + h)
    cr.stroke()


def _two_pin_body(cr, p1, p2, s, *, body_w_in, body_color, border_color, lead_color="#636363"):
    x1, y1 = p1[0] * s, p1[1] * s
    x2, y2 = p2[0] * s, p2[1] * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    cr.set_source_rgb(*_hex_to_rgb(lead_color.lstrip("#")))
    cr.set_line_width(1.4)
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)
    cr.stroke()

    cr.save()
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    cr.translate(cx, cy)
    cr.rotate(math.atan2(dy, dx))
    body_len = length * 0.55
    body_w = body_w_in * s
    cr.set_source_rgb(*_hex_to_rgb(body_color))
    cr.rectangle(-body_len / 2, -body_w / 2, body_len, body_w)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(border_color))
    cr.set_line_width(0.8)
    cr.stroke()
    cr.restore()


def _draw_text(cr, x, y, text, *, size=8, anchor="middle", color=(0, 0, 0)):
    cr.set_source_rgb(*color)
    cr.set_font_size(size)
    ext = cr.text_extents(text)
    if anchor == "middle":
        dx = -ext.width / 2
    elif anchor == "end":
        dx = -ext.width
    else:
        dx = 0
    cr.move_to(x + dx, y)
    cr.show_text(text)


def _value_label(cr, x1, y1, x2, y2, s, name, value, display):
    if display == "NONE":
        return
    if display == "NAME":
        text = name
    elif display == "VALUE":
        text = value or name
    elif display == "BOTH":
        text = f"{name} {value}" if value else name
    else:
        text = value or name
    cx = (x1 + x2) / 2 * s
    cy = (y1 + y2) / 2 * s - 7
    _draw_text(cr, cx, cy, text)


def _render_resistor(cr, c: Resistor, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.1, body_color=c.body_color, border_color=c.border_color,
    )
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_film_cap(cr, c: RadialFilmCapacitor, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.18, body_color=c.body_color, border_color=c.border_color,
    )
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_ceramic_cap(cr, c: RadialCeramicDiskCapacitor, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    cr.set_source_rgb(*_hex_to_rgb("#636363"))
    cr.set_line_width(1.2)
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)
    cr.stroke()
    r = max(8.0, math.hypot(x2 - x1, y2 - y1) * 0.32)
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(0.8)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_electrolytic(cr, c: RadialElectrolytic, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.3, body_color=c.body_color, border_color=c.border_color,
    )
    pos = (c.x2, c.y2) if not c.invert else (c.x1, c.y1)
    cr.set_source_rgb(*_hex_to_rgb("#ff8888"))
    cr.arc(pos[0] * s, pos[1] * s, 2.5, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb("#aa3333"))
    cr.set_line_width(0.6)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_pot(cr, c: PotentiometerPanel, s: float) -> None:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = _measure_to_inches(c.body_diameter) * s / 2
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(*_hex_to_rgb(c.wafer_color))
        cr.arc(px * s, py * s, 3, 0, 2 * math.pi)
        cr.fill_preserve()
        cr.set_source_rgb(0.27, 0.27, 0.27)
        cr.set_line_width(0.6)
        cr.stroke()
    _draw_text(cr, cx, cy + 4, f"{c.name} {c.resistance}", size=9)


def _render_diode(cr, c: DiodePlastic, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.08, body_color=c.body_color, border_color=c.border_color,
    )
    # Cathode band
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    bx = x1 + ux * length * 0.7
    by = y1 + uy * length * 0.7
    cr.save()
    cr.translate(bx, by)
    cr.rotate(math.atan2(dy, dx))
    cr.set_source_rgb(*_hex_to_rgb(c.marker_color))
    cr.rectangle(-1.5, -4, 3, 8)
    cr.fill()
    cr.restore()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_led(cr, c: LED, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    r = max(_measure_to_inches(c.length) * s / 2, 6.0)
    cr.set_source_rgb(0.39, 0.39, 0.39)
    cr.set_line_width(1.2)
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)
    cr.stroke()
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), 0.85)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_transistor(cr, c: TransistorTO92, s: float) -> None:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = 0.12 * s
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.arc(cx, cy, r, math.pi, 2 * math.pi)
    cr.close_path()
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(*_hex_to_rgb(c.lead_color))
        cr.set_line_width(1.2)
        cr.move_to(px * s, py * s)
        cr.line_to(cx, cy)
        cr.stroke()
        cr.set_source_rgb(0, 0, 0)
        cr.arc(px * s, py * s, 2, 0, 2 * math.pi)
        cr.fill()
    _draw_text(cr, cx, cy + 3, c.name, size=8, color=_hex_to_rgb(c.label_color))
    if c.value:
        _draw_text(cr, cx, cy + r + 10, c.value, size=8)


def _render_dil(cr, c: DIL_IC, s: float) -> None:
    n_pins = int(c.pin_count.lstrip("_"))
    rows = n_pins // 2
    pin_spacing_in = _measure_to_inches(c.pin_spacing)
    row_spacing_in = _measure_to_inches(c.row_spacing)
    if c.orientation in ("DEFAULT", "_180"):
        body_w = row_spacing_in * s
        body_h = (rows - 1) * pin_spacing_in * s + 0.1 * s
        body_x = c.x * s - body_w * 0.05
        body_y = c.y * s - 0.05 * s
    else:
        body_w = (rows - 1) * pin_spacing_in * s + 0.1 * s
        body_h = row_spacing_in * s
        body_x = c.x * s - 0.05 * s
        body_y = c.y * s - body_h * 0.05
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.rectangle(body_x, body_y, body_w, body_h)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    cr.set_source_rgb(*_hex_to_rgb(c.indent_color))
    cr.arc(body_x + 6, body_y + 6, 2, 0, 2 * math.pi)
    cr.fill()
    if c.orientation in ("DEFAULT", "_180"):
        for i in range(rows):
            y = c.y * s + i * pin_spacing_in * s
            cr.set_source_rgb(0, 0, 0)
            cr.arc(c.x * s, y, 2, 0, 2 * math.pi)
            cr.fill()
            cr.arc(c.x * s + row_spacing_in * s, y, 2, 0, 2 * math.pi)
            cr.fill()
    _draw_text(
        cr, body_x + body_w / 2, body_y + body_h / 2 + 3,
        c.value or c.name, size=9, color=_hex_to_rgb(c.label_color)
    )


def _render_trace(cr, c: CopperTrace, s: float) -> None:
    pts = list(c.points)
    if len(pts) < 2:
        return
    cr.set_source_rgba(*_hex_to_rgb(c.lead_color), 0.85)
    cr.set_line_width(max(2.0, _measure_to_inches(c.thickness) * s))
    cr.set_line_cap(1)  # ROUND
    cr.set_line_join(1)
    cr.move_to(pts[0][0] * s, pts[0][1] * s)
    for x, y in pts[1:]:
        cr.line_to(x * s, y * s)
    cr.stroke()


def _render_jumper(cr, c: Jumper, s: float) -> None:
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.6)
    if c.style == "DASHED":
        cr.set_dash([5, 3])
    elif c.style == "DOTTED":
        cr.set_dash([1, 3])
    cr.move_to(c.x1 * s, c.y1 * s)
    cr.line_to(c.x2 * s, c.y2 * s)
    cr.stroke()
    cr.set_dash([])


def _render_hookup_wire(cr, c: HookupWire, s: float) -> None:
    pts = list(c.points)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.8)
    cr.set_line_cap(1)
    if len(pts) == 2:
        cr.move_to(pts[0][0] * s, pts[0][1] * s)
        cr.line_to(pts[1][0] * s, pts[1][1] * s)
    else:
        p0, p1, p2, p3 = pts
        cr.move_to(p0[0] * s, p0[1] * s)
        cr.curve_to(p1[0] * s, p1[1] * s, p2[0] * s, p2[1] * s, p3[0] * s, p3[1] * s)
    cr.stroke()


def _render_solder_pad(cr, c: SolderPad, s: float) -> None:
    r = _measure_to_inches(c.size) * s / 2
    hole = _measure_to_inches(c.hole_size) * s / 2
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.arc(c.x * s, c.y * s, r, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.arc(c.x * s, c.y * s, hole, 0, 2 * math.pi)
    cr.fill()


def _render_trace_cut(cr, c: TraceCut, s: float) -> None:
    size_px = _measure_to_inches(c.size) * s
    cr.set_source_rgb(*_hex_to_rgb(c.fill_color))
    cr.rectangle(c.x * s - size_px / 2, c.y * s - size_px / 2, size_px, size_px)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    _draw_text(cr, c.x * s + size_px / 2 + 8, c.y * s + 3, "cut", size=7, color=(0.5, 0.5, 0.5), anchor="start")


def _render_mini_toggle(cr, c: MiniToggleSwitch, s: float) -> None:
    pts = c._control_points()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad_in = 0.1
    box_x = (min(xs) - pad_in) * s
    box_y = (min(ys) - pad_in) * s
    box_w = (max(xs) - min(xs) + 2 * pad_in) * s
    box_h = (max(ys) - min(ys) + 2 * pad_in) * s
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), 0.7)
    cr.rectangle(box_x, box_y, box_w, box_h)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(0.87, 0.87, 0.87)
        cr.arc(px * s, py * s, 3, 0, 2 * math.pi)
        cr.fill_preserve()
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.set_line_width(0.8)
        cr.stroke()
    label = c.switch_type.lstrip("_")
    _draw_text(cr, box_x + box_w / 2, box_y - 4, f"{c.name} {label}", size=9)


def _render_dc_jack(cr, c: PlasticDCJack, s: float) -> None:
    cx = c.x * s + 6
    cy = c.y * s + 10
    cr.set_source_rgb(0.13, 0.13, 0.13)
    cr.rectangle(c.x * s - 4, c.y * s - 4, 24, 28)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1)
    cr.stroke()
    cr.set_source_rgb(0.27, 0.27, 0.27)
    cr.arc(cx, cy, 6, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(0, 0, 0)
    cr.arc(cx, cy, 2, 0, 2 * math.pi)
    cr.fill()
    _draw_text(cr, c.x * s + 8, c.y * s + 30, f"{c.name} 9V", size=8, anchor="start")


def _render_open_jack(cr, c: OpenJack1_4, s: float) -> None:
    cx, cy = c.x * s, c.y * s + 10
    cr.set_source_rgb(0.8, 0.8, 0.8)
    cr.arc(cx, cy, 14, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(0.27, 0.27, 0.27)
    cr.set_line_width(1)
    cr.stroke()
    cr.set_source_rgb(0.13, 0.13, 0.13)
    cr.arc(cx, cy, 5, 0, 2 * math.pi)
    cr.fill()
    _draw_text(cr, cx, cy + 24, f'{c.name} 1/4"', size=8)


def _render_dot(cr, c: Dot, s: float) -> None:
    r = max(2.0, _measure_to_inches(c.size) * s / 2)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.arc(c.x * s, c.y * s, r, 0, 2 * math.pi)
    cr.fill()


def _render_eyelet(cr, c: Eyelet, s: float) -> None:
    r = _measure_to_inches(c.size) * s / 2
    hole = _measure_to_inches(c.hole_size) * s / 2
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.arc(c.x * s, c.y * s, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(0.27, 0.27, 0.27)
    cr.set_line_width(0.6)
    cr.stroke()
    cr.set_source_rgb(1, 1, 1)
    cr.arc(c.x * s, c.y * s, hole, 0, 2 * math.pi)
    cr.fill()


def _render_turret(cr, c: Turret, s: float) -> None:
    r = _measure_to_inches(c.size) * s / 2
    hole = _measure_to_inches(c.hole_size) * s / 2
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.arc(c.x * s, c.y * s, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(0.38, 0.25, 0)
    cr.set_line_width(0.6)
    cr.stroke()
    cr.set_source_rgb(0, 0, 0)
    cr.arc(c.x * s, c.y * s, hole, 0, 2 * math.pi)
    cr.fill()


def _render_line(cr, c: Line, s: float) -> None:
    pts = list(c.points)
    if len(pts) < 2:
        return
    cr.set_source_rgb(*_hex_to_rgb(c.lead_color))
    cr.set_line_width(1.2)
    cr.move_to(pts[0][0] * s, pts[0][1] * s)
    for x, y in pts[1:]:
        cr.line_to(x * s, y * s)
    cr.stroke()


def _render_axial_film_cap(cr, c: AxialFilmCapacitor, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.22, body_color=c.body_color, border_color=c.border_color,
    )
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_axial_electrolytic(cr, c: AxialElectrolyticCapacitor, s: float) -> None:
    _two_pin_body(
        cr, (c.x1, c.y1), (c.x2, c.y2), s,
        body_w_in=0.22, body_color=c.body_color, border_color=c.border_color,
    )
    pos = (c.x2, c.y2) if not c.invert else (c.x1, c.y1)
    cr.set_source_rgb(*_hex_to_rgb(c.marker_color))
    cr.arc(pos[0] * s, pos[1] * s, 2.5, 0, 2 * math.pi)
    cr.fill()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_tube_socket(cr, c: TubeSocket, s: float) -> None:
    pts = c._control_points()
    cx = sum(p[0] for p in pts) / len(pts) * s
    cy = sum(p[1] for p in pts) / len(pts) * s
    r = _measure_to_inches(c.pin_circle_diameter) * s / 2 + 8
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.label_color))
    cr.set_line_width(1)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(0.13, 0.13, 0.13)
        cr.arc(px * s, py * s, 2.5, 0, 2 * math.pi)
        cr.fill()
    label = c.tube_type or c.name
    _draw_text(cr, cx, cy + 4, label, size=10)


def _render_rectangle(cr, c: Rectangle, s: float) -> None:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    cr.set_source_rgba(*_hex_to_rgb(c.color), 0.3)
    cr.rectangle(x, y, w, h)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_ellipse(cr, c: Ellipse, s: float) -> None:
    cx = (c.x1 + c.x2) / 2 * s
    cy = (c.y1 + c.y2) / 2 * s
    rx = abs(c.x2 - c.x1) / 2 * s
    ry = abs(c.y2 - c.y1) / 2 * s
    cr.save()
    cr.translate(cx, cy)
    cr.scale(1, ry / rx if rx else 1)
    cr.set_source_rgba(*_hex_to_rgb(c.color), 0.3)
    cr.arc(0, 0, rx, 0, 2 * math.pi)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()
    cr.restore()


def _render_resistor_symbol(cr, c: ResistorSymbol, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    amp = 5.0
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.5)
    cr.move_to(x1, y1)
    sx = x1 + ux * length * 0.2
    sy = y1 + uy * length * 0.2
    cr.line_to(sx, sy)
    for i in range(6):
        t = 0.2 + 0.6 * (i + 1) / 7
        side = 1 if i % 2 == 0 else -1
        cr.line_to(x1 + ux * length * t + nx * amp * side,
                   y1 + uy * length * t + ny * amp * side)
    cr.line_to(x1 + ux * length * 0.8, y1 + uy * length * 0.8)
    cr.line_to(x2, y2)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_capacitor_symbol(cr, c: CapacitorSymbol, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    gap = 4.0
    half_plate = 7.0
    p1x, p1y = cx - ux * gap / 2, cy - uy * gap / 2
    p2x, p2y = cx + ux * gap / 2, cy + uy * gap / 2
    cr.set_source_rgb(*_hex_to_rgb(c.lead_color))
    cr.set_line_width(1.2)
    cr.move_to(x1, y1); cr.line_to(p1x, p1y); cr.stroke()
    cr.move_to(p2x, p2y); cr.line_to(x2, y2); cr.stroke()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(2)
    cr.move_to(p1x - nx * half_plate, p1y - ny * half_plate)
    cr.line_to(p1x + nx * half_plate, p1y + ny * half_plate)
    cr.stroke()
    cr.move_to(p2x - nx * half_plate, p2y - ny * half_plate)
    cr.line_to(p2x + nx * half_plate, p2y + ny * half_plate)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_diode_symbol(cr, c: DiodeSymbol, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    cr.set_source_rgb(*_hex_to_rgb(c.lead_color))
    cr.set_line_width(1.2)
    cr.move_to(x1, y1); cr.line_to(x2, y2); cr.stroke()
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.move_to(cx - ux * 6, cy - uy * 6)
    cr.line_to(cx + nx * 5, cy + ny * 5)
    cr.line_to(cx - nx * 5, cy - ny * 5)
    cr.close_path()
    cr.fill()
    cr.set_line_width(2)
    cr.move_to(cx + nx * 5, cy + ny * 5)
    cr.line_to(cx - nx * 5, cy - ny * 5)
    cr.stroke()
    _value_label(cr, c.x1, c.y1, c.x2, c.y2, s, c.name, c.value, c.display)


def _render_bjt_symbol(cr, c: BJTSymbol, s: float) -> None:
    pts = c._control_points()
    base, col, emi, _ = pts
    bx, by = base[0] * s, base[1] * s
    cx, cy = col[0] * s, col[1] * s
    ex, ey = emi[0] * s, emi[1] * s
    jx, jy = (bx + cx + ex) / 3, (by + cy + ey) / 3
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    cr.arc(jx, jy, 12, 0, 2 * math.pi)
    cr.stroke()
    for pt in [(cx, cy), (ex, ey)]:
        cr.move_to(pt[0], pt[1])
        cr.line_to(jx, jy)
        cr.stroke()
    cr.move_to(bx, by)
    cr.line_to(jx - 6, jy)
    cr.stroke()
    arrow = (ex, ey) if c.polarity == "NPN" else (jx, jy)
    cr.arc(arrow[0], arrow[1], 2.5, 0, 2 * math.pi)
    cr.fill()
    label = c.value or c.name
    _draw_text(cr, jx + 14, jy + 4, f"{label} {c.polarity}", size=9, anchor="start")


def _render_ground_symbol(cr, c: GroundSymbol, s: float) -> None:
    x, y = c.x * s, c.y * s
    size_px = _measure_to_inches(c.size) * s
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    cr.move_to(x, y); cr.line_to(x, y + size_px * 0.4); cr.stroke()
    if c.type == "TRIANGLE":
        cr.move_to(x - size_px * 0.5, y + size_px * 0.4)
        cr.line_to(x + size_px * 0.5, y + size_px * 0.4)
        cr.line_to(x, y + size_px)
        cr.close_path()
        cr.fill()
    else:
        cr.set_line_width(1.5)
        for off, w in [(0.4, 0.5), (0.6, 0.3), (0.8, 0.15)]:
            cr.move_to(x - size_px * w, y + size_px * off)
            cr.line_to(x + size_px * w, y + size_px * off)
            cr.stroke()


def _render_curved_trace(cr, c: CurvedTrace, s: float) -> None:
    pts = list(c.points)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(max(2.0, _measure_to_inches(c.size) * s))
    cr.set_line_cap(1)
    if len(pts) == 2:
        cr.move_to(pts[0][0] * s, pts[0][1] * s)
        cr.line_to(pts[1][0] * s, pts[1][1] * s)
    else:
        p0, p1, p2, p3 = pts
        cr.move_to(p0[0] * s, p0[1] * s)
        cr.curve_to(p1[0] * s, p1[1] * s, p2[0] * s, p2[1] * s, p3[0] * s, p3[1] * s)
    cr.stroke()


def _render_trimmer(cr, c: TrimmerPotentiometer, s: float) -> None:
    pts = c._control_points()
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    cx = (min(xs) + max(xs)) / 2 * s
    cy = (min(ys) + max(ys)) / 2 * s
    size = 14
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.rectangle(cx - size, cy - size, 2 * size, 2 * size)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(0.13, 0.13, 0.13)
        cr.arc(px * s, py * s, 2, 0, 2 * math.pi)
        cr.fill()
    _draw_text(cr, cx, cy + 3, f"{c.name} {c.resistance}", size=8)


def _render_terminal_strip(cr, c: TerminalStrip, s: float) -> None:
    pts = c._control_points()
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    pad = 0.08
    x = (min(xs) - pad) * s
    y = (min(ys) - pad) * s
    w = (max(xs) - min(xs) + 2 * pad) * s
    h = (max(ys) - min(ys) + 2 * pad) * s
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.rectangle(x, y, w, h)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1)
    cr.stroke()
    for px, py in pts:
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.arc(px * s, py * s, 2.5, 0, 2 * math.pi)
        cr.fill()


def _render_image(cr, c: Image, s: float) -> None:
    x, y = c.x * s, c.y * s
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(x - 30, y - 30, 60, 60)
    cr.fill_preserve()
    cr.set_source_rgb(0.53, 0.53, 0.53)
    cr.set_dash([4, 3])
    cr.stroke()
    cr.set_dash([])
    _draw_text(cr, x, y + 4, "[image]", size=9, color=(0.53, 0.53, 0.53))


def _render_bom(cr, c: BOM, s: float) -> None:
    x, y = c.x * s, c.y * s
    size_px = _measure_to_inches(c.size) * s
    cr.set_source_rgb(1, 1, 1)
    cr.rectangle(x, y, size_px, size_px)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_dash([3, 2])
    cr.stroke()
    cr.set_dash([])
    _draw_text(cr, x + size_px / 2, y + size_px / 2 + 4, "BOM", size=10)


def _render_label(cr, c: Label, s: float) -> None:
    cr.save()
    weight = 1 if c.font_style in (1, 3) else 0
    slant = 1 if c.font_style in (2, 3) else 0
    cr.select_font_face("sans-serif", slant, weight)
    cr.set_font_size(c.font_size)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    ext = cr.text_extents(c.text)
    if c.horizontal_alignment == "CENTER":
        dx = -ext.width / 2
    elif c.horizontal_alignment == "RIGHT":
        dx = -ext.width
    else:
        dx = 0
    cr.move_to(c.x * s + dx, c.y * s)
    cr.show_text(c.text)
    cr.restore()


def _render_ground_fill(cr, c: GroundFill, s: float) -> None:
    pts = [(x * s, y * s) for x, y in c.points]
    if len(pts) < 3:
        return
    cr.move_to(*pts[0])
    for x, y in pts[1:]:
        cr.line_to(x, y)
    cr.close_path()
    cr.set_source_rgba(*_hex_to_rgb(c.color), 0.35)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_elliptical_cutout(cr, c: EllipticalCutout, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
    if rx == 0 or ry == 0:
        return
    cr.save()
    cr.translate(cx, cy)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()
    cr.set_source_rgba(*_hex_to_rgb(c.color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_pin_header(cr, c: PinHeader, s: float) -> None:
    for x, y in c.points:
        cr.arc(x * s, y * s, 4, 0, 2 * math.pi)
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(1.0)
        cr.stroke()


def _render_polygon(cr, c: Polygon, s: float) -> None:
    pts = [(x * s, y * s) for x, y in c.points]
    if len(pts) < 3:
        return
    cr.move_to(*pts[0])
    for x, y in pts[1:]:
        cr.line_to(x, y)
    cr.close_path()
    cr.set_source_rgba(*_hex_to_rgb(c.color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_wrap_label(cr, c: WrapLabel, s: float) -> None:
    cr.save()
    cr.select_font_face("sans-serif")
    cr.set_font_size(c.font_size)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    x = c.x1 * s
    y = c.y1 * s + c.font_size
    cr.move_to(x, y)
    cr.show_text(c.text)
    cr.restore()


def _render_diode_glass(cr, c: DiodeGlass, s: float) -> None:
    _render_diode_like(cr, c, s)


def _render_diode_like(cr, c, s: float) -> None:
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    body_len = max(length * 0.5, 14)
    body_w = 8
    px, py = -uy, ux
    hl = body_len / 2
    hw = body_w / 2
    cr.move_to(cx - ux * hl + px * hw, cy - uy * hl + py * hw)
    cr.line_to(cx + ux * hl + px * hw, cy + uy * hl + py * hw)
    cr.line_to(cx + ux * hl - px * hw, cy + uy * hl - py * hw)
    cr.line_to(cx - ux * hl - px * hw, cy - uy * hl - py * hw)
    cr.close_path()
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()
    cr.set_source_rgb(*_hex_to_rgb(c.lead_color))
    cr.set_line_width(1.2)
    cr.move_to(x1, y1)
    cr.line_to(cx - ux * hl, cy - uy * hl)
    cr.move_to(cx + ux * hl, cy + uy * hl)
    cr.line_to(x2, y2)
    cr.stroke()


def _render_pcb_text(cr, c: PCBText, s: float) -> None:
    cr.save()
    cr.select_font_face("monospace")
    cr.set_font_size(c.font_size)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.move_to(c.x * s, c.y * s + c.font_size)
    cr.show_text(c.text)
    cr.restore()


def _render_potentiometer_symbol(cr, c: PotentiometerSymbol, s: float) -> None:
    pts = c._control_points()
    sx = [p[0] * s for p in pts]
    sy = [p[1] * s for p in pts]
    cx, cy = sum(sx) / 3, sum(sy) / 3
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.0)
    cr.arc(cx, cy, 8, 0, 2 * math.pi)
    cr.stroke()
    for x, y in zip(sx, sy):
        cr.move_to(cx, cy)
        cr.line_to(x, y)
        cr.stroke()


def _render_closed_jack(cr, c: ClosedJack1_4, s: float) -> None:
    x, y = c.x * s, c.y * s
    cr.rectangle(x - 4, y - 4, 0.3 * s, 0.8 * s)
    cr.set_source_rgba(0.4, 0.4, 0.4, c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1.0)
    cr.stroke()


def _render_rca_jack(cr, c: RCAJack, s: float) -> None:
    x, y = c.x * s, c.y * s
    cr.arc(x, y, 0.12 * s, 0, 2 * math.pi)
    cr.set_source_rgba(0.7, 0.6, 0.3, c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1.0)
    cr.stroke()
    cr.arc(x, y, 0.04 * s, 0, 2 * math.pi)
    cr.set_source_rgb(0, 0, 0)
    cr.fill()


def _render_transformer_coil(cr, c: TransformerCoil, s: float) -> None:
    # A series of arcs from (x1,y1) to (x2,y2) to suggest the winding.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    bumps = max(3, int(L / 8))
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    for i in range(bumps):
        t1 = i / bumps
        t2 = (i + 1) / bumps
        ax, ay = x1 + dx * t1, y1 + dy * t1
        bx, by = x1 + dx * t2, y1 + dy * t2
        cx, cy = (ax + bx) / 2, (ay + by) / 2
        cr.arc(cx, cy, L / (bumps * 2), 0, math.pi)
    cr.stroke()


def _render_transformer_core(cr, c: TransformerCore, s: float) -> None:
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(2.0)
    cr.move_to(c.x1 * s, c.y1 * s)
    cr.line_to(c.x2 * s, c.y2 * s)
    cr.stroke()


def _render_triode_symbol(cr, c: TriodeSymbol, s: float) -> None:
    x, y = c.x * s, c.y * s
    r = 0.3 * s
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    cr.arc(x + r, y, r, 0, 2 * math.pi)
    cr.stroke()
    # Plate (top horizontal stub).
    cr.move_to(x + r - 6, y - r)
    cr.line_to(x + r + 6, y - r)
    cr.stroke()


def _render_single_coil_pickup(cr, c: SingleCoilPickup, s: float) -> None:
    # Stratocaster-style pickup body: rounded rectangle ~0.7 × 1.0 in.
    x, y = c.x * s, c.y * s
    w, h = 0.7 * s, 1.0 * s
    cr.rectangle(x - w / 2, y - h / 2, w, h)
    cr.set_source_rgba(*_hex_to_rgb(c.color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.base_color))
    cr.set_line_width(1.2)
    cr.stroke()
    # Pole pieces (6 dots along the y axis).
    cr.set_source_rgb(0.5, 0.5, 0.5)
    for i in range(6):
        py = y - h / 2 + (i + 0.5) * (h / 6)
        cr.arc(x, py, 2.5, 0, 2 * math.pi)
        cr.fill()


def _render_cliff_jack(cr, c: CliffJack1_4, s: float) -> None:
    # Body rectangle around the 5 control points.
    x = c.x * s
    y = c.y * s
    w = 0.4 * s
    h = 0.3 * s
    cr.rectangle(x - 4, y - 4, w, h)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_tag_strip(cr, c: TagStrip, s: float) -> None:
    ts = c.terminal_spacing.to_inches()
    h = (c.terminal_count - 1) * ts + 0.2
    cr.rectangle((c.x - 0.05) * s, (c.y - 0.1) * s, 0.3 * s, h * s)
    cr.set_source_rgba(*_hex_to_rgb(c.board_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0.2, 0.1, 0)
    cr.set_line_width(1.0)
    cr.stroke()
    for i in range(c.terminal_count):
        y = (c.y + i * ts) * s
        cr.arc(c.x * s, y, 3, 0, 2 * math.pi)
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0)
        cr.stroke()


def _render_pilot_lamp(cr, c: PilotLampHolder, s: float) -> None:
    cx, cy = c.x * s, c.y * s
    cr.arc(cx, cy, 12, 0, 2 * math.pi)
    cr.set_source_rgba(1, 0.85, 0.3, c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0.3, 0.2, 0)
    cr.set_line_width(1.0)
    cr.stroke()


def _render_multi_section_cap(cr, c: MultiSectionCapacitor, s: float) -> None:
    sections = len(c.values)
    h = sections * 0.2 + 0.1
    cr.rectangle((c.x - 0.15) * s, (c.y - 0.1) * s, 0.3 * s, h * s)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_tape_measure(cr, c: TapeMeasure, s: float) -> None:
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.0)
    cr.move_to(c.x1 * s, c.y1 * s)
    cr.line_to(c.x2 * s, c.y2 * s)
    cr.stroke()
    # Arrow heads at each end (small triangles).
    for (ex, ey, ox, oy) in [(c.x1, c.y1, c.x2, c.y2), (c.x2, c.y2, c.x1, c.y1)]:
        cr.move_to(ex * s, ey * s)
        cr.line_to(ox * s, oy * s)
    cr.stroke()


def _render_fuse_holder(cr, c: FuseHolderPanel, s: float) -> None:
    cr.rectangle((c.x - 0.05) * s, c.y * s, 0.1 * s, 0.2 * s)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_audio_transformer(cr, c: AudioTransformer, s: float) -> None:
    w = c.coil_width.to_inches() * s
    h = c.coil_length.to_inches() * s
    cr.rectangle(c.x * s - w / 2, c.y * s, w, h)
    cr.set_source_rgba(*_hex_to_rgb(c.coil_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.core_color))
    cr.set_line_width(1.5)
    cr.stroke()


def _render_led_symbol(cr, c: LEDSymbol, s: float) -> None:
    # Triangle pointing along x1→x2.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    size = 8
    cr.move_to(cx - ux * size, cy - uy * size + 0)
    cr.line_to(cx + ux * size, cy + uy * size)
    cr.line_to(cx + px * size, cy + py * size)
    cr.close_path()
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1.0)
    cr.stroke()


def _render_sil_ic(cr, c: SIL_IC, s: float) -> None:
    n = int(c.pin_count.lstrip("_"))
    ps = c.pin_spacing.to_inches()
    w = (n - 1) * ps + 0.1
    cr.rectangle((c.x - 0.05) * s, (c.y - 0.1) * s, w * s, 0.25 * s)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_chassis_panel(cr, c: ChassisPanel, s: float) -> None:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    cr.rectangle(x, y, w, h)
    cr.set_source_rgba(*_hex_to_rgb(c.color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.5)
    cr.stroke()


def _render_transistor_to1(cr, c: TransistorTO1, s: float) -> None:
    cx, cy = c.x * s, (c.y + c.pin_spacing.to_inches()) * s
    cr.arc(cx, cy, 0.18 * s, 0, 2 * math.pi)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_transistor_to220(cr, c: TransistorTO220, s: float) -> None:
    ps = c.pin_spacing.to_inches()
    cr.rectangle((c.x - 0.15) * s, (c.y - 0.05) * s, 0.3 * s, (2 * ps + 0.1) * s)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_iec_socket(cr, c: IECSocket, s: float) -> None:
    cr.rectangle((c.x - 0.3) * s, (c.y - 0.05) * s, 0.6 * s, 0.3 * s)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_tantalum_cap(cr, c: TantalumCapacitor, s: float) -> None:
    _render_axial_film_cap(cr, c, s)  # same shape, different colors


def _render_eyelet_board(cr, c: EyeletBoard, s: float) -> None:
    cr.rectangle(c.x1 * s, c.y1 * s, (c.x2 - c.x1) * s, (c.y2 - c.y1) * s)
    cr.set_source_rgba(*_hex_to_rgb(c.board_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_inductor_symbol(cr, c: InductorSymbol, s: float) -> None:
    # Series of small arcs along the lead direction.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    bumps = 4
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    for i in range(bumps):
        t = (i + 0.5) / bumps
        cx = x1 + dx * t
        cy = y1 + dy * t
        cr.arc(cx, cy, L / (bumps * 2), 0, math.pi)
    cr.stroke()


def _render_pentode_symbol(cr, c: PentodeSymbol, s: float) -> None:
    x, y = (c.x + 0.3) * s, (c.y + 0.1) * s
    cr.arc(x, y, 0.3 * s, 0, 2 * math.pi)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_breadboard(cr, c: Breadboard, s: float) -> None:
    # Half breadboard ≈ 3.3 × 2.2 in; rough placeholder.
    sz = {"Half": (3.3, 2.2), "Full": (6.5, 2.2), "Mini": (1.7, 1.3)}.get(c.size, (3.3, 2.2))
    cr.rectangle(c.x * s, c.y * s, sz[0] * s, sz[1] * s)
    cr.set_source_rgb(0.95, 0.95, 0.95)
    cr.fill_preserve()
    cr.set_source_rgb(0.5, 0.5, 0.5)
    cr.set_line_width(1.0)
    cr.stroke()


def _render_lever_switch(cr, c: LeverSwitch, s: float) -> None:
    n = c._pin_count()
    h = (n // 2) * 0.1 + 0.1
    cr.rectangle((c.x - 0.05) * s, (c.y - 0.05) * s, 0.3 * s, h * s)
    cr.set_source_rgba(0.6, 0.6, 0.6, c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1.0)
    cr.stroke()


def _render_zener_symbol(cr, c: ZenerDiodeSymbol, s: float) -> None:
    # Same triangle as a regular diode symbol.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    size = 8
    cr.move_to(cx - size, cy - size)
    cr.line_to(cx + size, cy)
    cr.line_to(cx - size, cy + size)
    cr.close_path()
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.fill()


def _render_marshall_perf(cr, c: MarshallPerfBoard, s: float) -> None:
    cr.rectangle(c.x1 * s, c.y1 * s, (c.x2 - c.x1) * s, (c.y2 - c.y1) * s)
    cr.set_source_rgba(*_hex_to_rgb(c.board_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.0)
    cr.stroke()


def _fill_stroke_rect(cr, x, y, w, h, fill, stroke, alpha=1.0, line_w=1.0):
    cr.rectangle(x, y, w, h)
    cr.set_source_rgba(*_hex_to_rgb(fill), alpha)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(stroke))
    cr.set_line_width(line_w)
    cr.stroke()


def _render_mini_relay(cr, c: MiniRelay, s: float) -> None:
    _fill_stroke_rect(cr, (c.x - 0.05) * s, (c.y - 0.05) * s,
                      0.3 * s, 0.4 * s, "404040", "000000", c.alpha / 255)


def _render_rect_cutout(cr, c: RectangularCutout, s: float) -> None:
    x = min(c.x1, c.x2) * s
    y = min(c.y1, c.y2) * s
    w = abs(c.x2 - c.x1) * s
    h = abs(c.y2 - c.y1) * s
    _fill_stroke_rect(cr, x, y, w, h, c.color, c.border_color, c.alpha / 255)


def _render_bass_pickup(cr, c, s, w=0.4, h=0.5) -> None:
    _fill_stroke_rect(cr, (c.x - w / 2) * s, c.y * s, w * s, h * s,
                      c.color, c.pole_color, c.alpha / 255, 1.2)
    cr.set_source_rgb(*_hex_to_rgb(c.pole_color))
    for i in range(4):
        cr.arc(c.x * s, (c.y + (i + 0.5) * (h / 4)) * s, 2, 0, 2 * math.pi)
        cr.fill()


def _render_jazz_bass_pickup(cr, c: JazzBassPickup, s: float) -> None:
    _render_bass_pickup(cr, c, s)


def _render_pbass_pickup(cr, c: PBassPickup, s: float) -> None:
    _render_bass_pickup(cr, c, s)


def _render_humbucker(cr, c: HumbuckerPickup, s: float) -> None:
    _fill_stroke_rect(cr, (c.x - 0.4) * s, c.y * s, 0.8 * s, 1.4 * s,
                      c.color, c.pole_color, c.alpha / 255, 1.2)


def _render_lp_switch(cr, c: LPSwitch, s: float) -> None:
    _fill_stroke_rect(cr, (c.x - 0.05) * s, c.y * s, 0.4 * s, 1.4 * s,
                      "606060", "000000", c.alpha / 255)


def _render_battery_snap_9v(cr, c: BatterySnap9V, s: float) -> None:
    _fill_stroke_rect(cr, (c.x - 0.15) * s, c.y * s, 0.3 * s, 0.5 * s,
                      c.color, "000000", c.alpha / 255)


def _render_ic_symbol(cr, c: ICSymbol, s: float) -> None:
    # Op-amp triangle pointing +X.
    x, y = c.x * s, c.y * s
    cr.move_to(x, y)
    cr.line_to(x, y + 0.2 * s)
    cr.line_to(x + 0.4 * s, y + 0.1 * s)
    cr.close_path()
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_rotary_selector(cr, c: RotarySelectorSwitch, s: float) -> None:
    cr.arc(c.x * s, c.y * s, 0.4 * s, 0, 2 * math.pi)
    cr.set_source_rgba(0.7, 0.7, 0.7, c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(0, 0, 0)
    cr.set_line_width(1.2)
    cr.stroke()


def _render_battery_symbol(cr, c: BatterySymbol, s: float) -> None:
    # Two parallel lines (long + short) at the midpoint.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.5)
    # Long line at cx-4, short at cx+4 (perpendicular).
    for offset, half in ((-3, 8), (3, 4)):
        sx, sy = cx + ux * offset - px * half, cy + uy * offset - py * half
        ex, ey = cx + ux * offset + px * half, cy + uy * offset + py * half
        cr.move_to(sx, sy); cr.line_to(ex, ey)
    cr.stroke()


def _render_electrolytic_can(cr, c: ElectrolyticCanCapacitor, s: float) -> None:
    cr.arc(c.x * s, (c.y + 1.0) * s, s, 0, 2 * math.pi)
    cr.set_source_rgba(*_hex_to_rgb(c.body_color), c.alpha / 255)
    cr.fill_preserve()
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_tripad_board(cr, c: TriPadBoard, s: float) -> None:
    _fill_stroke_rect(cr, c.x1 * s, c.y1 * s,
                      (c.x2 - c.x1) * s, (c.y2 - c.y1) * s,
                      c.board_color, c.border_color, c.alpha / 255)


def _render_fuse_symbol(cr, c: FuseSymbol, s: float) -> None:
    # A rectangle outline with no fill (just the body).
    cx, cy = (c.x1 + c.x2) / 2 * s, (c.y1 + c.y2) / 2 * s
    dx, dy = (c.x2 - c.x1) * s, (c.y2 - c.y1) * s
    L = math.hypot(dx, dy) or 1
    body_l = max(L * 0.6, 14)
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(math.atan2(dy, dx))
    cr.rectangle(-body_l / 2, -4, body_l, 8)
    cr.set_source_rgb(*_hex_to_rgb(c.border_color))
    cr.set_line_width(1.2)
    cr.stroke()
    cr.restore()


def _render_tube_diode(cr, c: TubeDiodeSymbol, s: float) -> None:
    x, y = (c.x + 0.15) * s, (c.y + 0.2) * s
    cr.arc(x, y, 0.25 * s, 0, 2 * math.pi)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.2)
    cr.stroke()


def _render_jfet_symbol(cr, c: JFETSymbol, s: float) -> None:
    x, y = c.x * s, c.y * s
    cr.arc(x + 0.1 * s, y, 0.15 * s, 0, 2 * math.pi)
    cr.set_source_rgb(*_hex_to_rgb(c.color))
    cr.set_line_width(1.0)
    cr.stroke()


def _render_crystal(cr, c: CrystalOscillator, s: float) -> None:
    _fill_stroke_rect(cr,
                      min(c.x1, c.x2) * s - 6,
                      (min(c.y1, c.y2) - 0.1) * s,
                      abs(c.x2 - c.x1) * s + 12,
                      c.width.to_inches() * s,
                      c.body_color, c.border_color, c.alpha / 255)


def _render_neutrik_jack(cr, c: NeutrikJack1_4, s: float) -> None:
    _fill_stroke_rect(cr, c.x * s, (c.y - 0.5) * s,
                      0.7 * s, 0.5 * s, "303030", "000000", c.alpha / 255)


def _render_transistor_to126(cr, c: TransistorTO126, s: float) -> None:
    ps = c.pin_spacing.to_inches()
    _fill_stroke_rect(cr, (c.x - 0.15) * s, (c.y - 0.05) * s,
                      0.3 * s, (2 * ps + 0.1) * s,
                      c.body_color, c.border_color, c.alpha / 255)


def _render_p90_pickup(cr, c: P90Pickup, s: float) -> None:
    _fill_stroke_rect(cr, (c.x - 0.5) * s, c.y * s, 1.0 * s, 1.5 * s,
                      c.color, "404040", c.alpha / 255, 1.2)


def _render_smd_resistor(cr, c: SMDResistor, s: float) -> None:
    sz = float(c.size.lstrip("_"))
    len_in = sz / 1000
    _fill_stroke_rect(cr, c.x * s, (c.y - len_in / 4) * s,
                      len_in * s, (len_in / 2) * s,
                      c.body_color, c.border_color, c.alpha / 255)


def _render_smd_capacitor(cr, c: SMDCapacitor, s: float) -> None:
    sz = float(c.size.lstrip("_"))
    len_in = sz / 1000
    _fill_stroke_rect(cr, c.x * s, (c.y - len_in / 4) * s,
                      len_in * s, (len_in / 2) * s,
                      c.body_color, c.border_color, c.alpha / 255)


def _render_schottky_symbol(cr, c: SchottkyDiodeSymbol, s: float) -> None:
    # Triangle pointing along x1→x2.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    size = 8
    cr.move_to(cx - size, cy - size)
    cr.line_to(cx + size, cy)
    cr.line_to(cx - size, cy + size)
    cr.close_path()
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.fill()


def _render_bridge_rectifier(cr, c: BridgeRectifier, s: float) -> None:
    _fill_stroke_rect(cr, c.x * s, c.y * s, 0.2 * s, 0.2 * s,
                      c.body_color, c.border_color, c.alpha / 255)


def _render_photo_diode_symbol(cr, c: PhotoDiodeSymbol, s: float) -> None:
    # Triangle + a couple of small arrows pointing in.
    x1, y1 = c.x1 * s, c.y1 * s
    x2, y2 = c.x2 * s, c.y2 * s
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    size = 8
    cr.move_to(cx - size, cy - size)
    cr.line_to(cx + size, cy)
    cr.line_to(cx - size, cy + size)
    cr.close_path()
    cr.set_source_rgb(*_hex_to_rgb(c.body_color))
    cr.fill()


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
    Image: _render_image,
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
    TransistorTO220: _render_transistor_to220,
    IECSocket: _render_iec_socket,
    TantalumCapacitor: _render_tantalum_cap,
    EyeletBoard: _render_eyelet_board,
    InductorSymbol: _render_inductor_symbol,
    PentodeSymbol: _render_pentode_symbol,
    Breadboard: _render_breadboard,
    LeverSwitch: _render_lever_switch,
    ZenerDiodeSymbol: _render_zener_symbol,
    MarshallPerfBoard: _render_marshall_perf,
    MiniRelay: _render_mini_relay,
    RectangularCutout: _render_rect_cutout,
    JazzBassPickup: _render_jazz_bass_pickup,
    PBassPickup: _render_pbass_pickup,
    HumbuckerPickup: _render_humbucker,
    LPSwitch: _render_lp_switch,
    BatterySnap9V: _render_battery_snap_9v,
    ICSymbol: _render_ic_symbol,
    RotarySelectorSwitch: _render_rotary_selector,
    BatterySymbol: _render_battery_symbol,
    ElectrolyticCanCapacitor: _render_electrolytic_can,
    TriPadBoard: _render_tripad_board,
    FuseSymbol: _render_fuse_symbol,
    TubeDiodeSymbol: _render_tube_diode,
    JFETSymbol: _render_jfet_symbol,
    CrystalOscillator: _render_crystal,
    NeutrikJack1_4: _render_neutrik_jack,
    TransistorTO126: _render_transistor_to126,
    P90Pickup: _render_p90_pickup,
    SMDResistor: _render_smd_resistor,
    SMDCapacitor: _render_smd_capacitor,
    SchottkyDiodeSymbol: _render_schottky_symbol,
    BridgeRectifier: _render_bridge_rectifier,
    PhotoDiodeSymbol: _render_photo_diode_symbol,
}
