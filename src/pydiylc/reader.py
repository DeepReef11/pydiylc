"""Read .diy XML files back into pydiylc Projects.

This is the inverse of the per-component emitters in ``components.py``.
It is intentionally tolerant: unknown component types are skipped (with a
warning recorded in ``Project.metadata['read_warnings']``) so that the
parser works on real-world DIYLC files using components pydiylc does not
yet model.

For the components pydiylc does know about, the read is faithful enough
that ``emit -> read -> emit`` is stable (round-trip-clean) up to attribute
ordering. Two-pin components are reconstructed from the [p1, p2, mid]
points format DIYLC writes, dropping the midpoint.

Usage::

    from pydiylc import Project
    p = Project.read("layout.diy")
    print(p.title, len(p.components))
"""

from __future__ import annotations

import dataclasses
import re
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .core import Measure, Project
from .components import ALL_COMPONENTS, Component


# Map DIYLC element tag → pydiylc Component class.
# Modern (4.x+) files use the short prefix `diylc.<category>.<Name>`.
# Older v3 / XStream-serialized files use the full Java package path
# `org.diylc.components.<category>.<Name>`. We accept both.
#
# XStream class-name escaping: every literal underscore in a Java class name
# becomes a double underscore in the XML tag (so `DIL_IC` ↔ `DIL__IC`,
# `OpenJack1_4` ↔ `OpenJack1__4`, `CliffJack1_4` ↔ `CliffJack1__4`). We
# register both the bare and the XStream-escaped form for every component
# so old + new files read identically.
_TAG_TO_CLASS: dict[str, type[Component]] = {}


def _xstream_escape(tag: str) -> str:
    """Convert a Java-style tag to its XStream XML form (_ → __)."""
    # Only the class-name segment (last dotted component) is escaped — the
    # package path itself uses dots, not underscores. Splitting at the last
    # dot, escaping the class name, and rejoining matches XStream exactly.
    if "." not in tag:
        return tag.replace("_", "__")
    pkg, name = tag.rsplit(".", 1)
    return f"{pkg}.{name.replace('_', '__')}"


for _cls in ALL_COMPONENTS:
    short = _cls.__diylc_class__
    _TAG_TO_CLASS[short] = _cls
    # diylc.connectivity.SolderPad → org.diylc.components.connectivity.SolderPad
    parts = short.split(".")
    if len(parts) >= 3:
        full = ".".join(["org.diylc.components"] + parts[1:])
        _TAG_TO_CLASS[full] = _cls
    # XStream-escaped variants — only useful when the class name has a "_".
    if "_" in short.rsplit(".", 1)[-1]:
        _TAG_TO_CLASS[_xstream_escape(short)] = _cls
        if len(parts) >= 3:
            _TAG_TO_CLASS[_xstream_escape(full)] = _cls

# A few alternate spellings that resolve to the same Python class as their
# modern equivalent (component-rename aliases, not just escape variants).
from .components import HookupWire as _HookupWire  # noqa: E402

# TwistedWire is a HookupWire variant; we render it as a hookup wire with no
# fidelity loss for the polyline shape (the twist is purely cosmetic).
_TAG_TO_CLASS["diylc.connectivity.TwistedWire"] = _HookupWire
_TAG_TO_CLASS["org.diylc.components.connectivity.TwistedWire"] = _HookupWire

# Some upstream child tags don't match our field names cleanly. These are the
# exceptions; everything else uses _camel_to_snake().
_FIELD_RENAMES: dict[str, dict[str, str]] = {
    # default rename table — applies to every component unless overridden
    "*": {
        "labelOriantation": "label_orientation",  # upstream typo
    },
    # per-component overrides:
    "diylc.boards.BlankBoard": {},
    "diylc.boards.PerfBoard": {},
    "diylc.boards.VeroBoard": {},
    "diylc.tube.TubeSocket": {
        # Upstream <type> conflicts with Python builtin; we expose it as
        # `tube_type` on the dataclass.
        "type": "tube_type",
    },
}


def _camel_to_snake(name: str) -> str:
    """Convert camelCase / PascalCase to snake_case."""
    # Insert underscore before each uppercase letter that follows a lowercase
    # letter or another uppercase letter followed by a lowercase one.
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def _renamed_field(diylc_class: str, child_tag: str) -> str:
    """Resolve a DIYLC child tag to a Python field name.

    ``diylc_class`` is normalized to the short ``diylc.*`` prefix so per-class
    overrides apply uniformly to old and new XStream formats.
    """
    short = diylc_class
    if short.startswith("org.diylc.components."):
        short = "diylc." + short[len("org.diylc.components."):]
    table = _FIELD_RENAMES.get(short, {})
    if child_tag in table:
        return table[child_tag]
    common = _FIELD_RENAMES["*"]
    if child_tag in common:
        return common[child_tag]
    return _camel_to_snake(child_tag)


def _parse_point(el: ET.Element) -> tuple[float, float]:
    return float(el.get("x", "0")), float(el.get("y", "0"))


def _point_children(parent: ET.Element) -> list[ET.Element]:
    """Children of a points/controlPoints container.

    Modern files use ``<point x="..." y="..."/>``; v3 XStream files use
    ``<java.awt.Point x="..." y="..."/>`` (the Java class name leaks through
    the serializer). Both have the same x/y attribute shape; we accept both.
    """
    return [c for c in parent if c.tag in ("point", "java.awt.Point")]


def _parse_measure(el: ET.Element) -> Measure:
    """Parse a Measure-shaped XML element.

    Two forms in the wild:
      - Modern: ``<size value="0.09" unit="in"/>`` (attributes).
      - v3 XStream: ``<size><value>0.09</value><unit class="...">in</unit></size>``
        (nested elements).
    """
    if el.get("value") is not None and el.get("unit") is not None:
        return Measure(float(el.get("value", "0")), el.get("unit", "in"))
    # Fall back to the nested form.
    v_el = el.find("value")
    u_el = el.find("unit")
    if v_el is not None and v_el.text is not None:
        try:
            v = float(v_el.text.strip())
        except ValueError:
            v = 0.0
        u = (u_el.text or "in").strip() if u_el is not None else "in"
        return Measure(v, u)
    return Measure(0.0, "in")


def _looks_like_measure(el: ET.Element) -> bool:
    """True if ``el`` represents a Measure (attr or nested form)."""
    if el.get("value") is not None and el.get("unit") is not None:
        return True
    # Nested form: a <value> child plus a <unit> child.
    return el.find("value") is not None and el.find("unit") is not None


def _parse_color(el: ET.Element) -> str:
    """Parse a color element.

    Two forms in the wild:
      - Modern: ``<bodyColor hex="abc123"/>`` (single attribute).
      - v3 XStream: ``<bodyColor><red>248</red><green>235</green>
        <blue>179</blue><alpha>255</alpha></bodyColor>`` (nested ints).
    """
    if el.get("hex") is not None:
        return el.get("hex", "000000")
    r_el = el.find("red")
    g_el = el.find("green")
    b_el = el.find("blue")
    if r_el is not None and g_el is not None and b_el is not None:
        try:
            r = int((r_el.text or "0").strip())
            g = int((g_el.text or "0").strip())
            b = int((b_el.text or "0").strip())
            return f"{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"
        except ValueError:
            pass
    return "000000"


def _looks_like_color(el: ET.Element) -> bool:
    """True if ``el`` represents a color (attr or nested form)."""
    if el.get("hex") is not None:
        return True
    return (
        el.find("red") is not None
        and el.find("green") is not None
        and el.find("blue") is not None
    )


def _parse_bool(text: str | None) -> bool:
    return (text or "").strip().lower() == "true"


def _set_two_pin_coords(values: dict[str, Any], pts: list[tuple[float, float]]) -> None:
    """Two-pin components: take p1, p2 from the points (ignore midpoint if present)."""
    if not pts:
        return
    p1 = pts[0]
    p2 = pts[1] if len(pts) >= 2 else pts[0]
    values["x1"], values["y1"] = p1
    values["x2"], values["y2"] = p2


def _set_single_anchor(values: dict[str, Any], pts: list[tuple[float, float]]) -> None:
    if not pts:
        return
    values["x"], values["y"] = pts[0]


def _component_from_element(el: ET.Element, warnings_out: list[str]) -> Component | None:
    cls = _TAG_TO_CLASS.get(el.tag)
    if cls is None:
        warnings_out.append(f"unknown component type: {el.tag}")
        return None

    field_names = {f.name for f in dataclasses.fields(cls)}
    measure_fields = {
        f.name for f in dataclasses.fields(cls)
        if f.type is Measure or (isinstance(f.type, str) and f.type == "Measure")
    }

    # Components that store value as a string-form unit (e.g. Resistor.value="10K",
    # PotentiometerPanel.resistance="100K"). For these, when the XML has
    # <value value="10" unit="K"/>, we serialize back to "10K" instead of
    # storing a Measure.
    _UNIT_VALUE_AS_STRING = {
        ("diylc.passive.Resistor", "value"),
        ("diylc.passive.RadialFilmCapacitor", "value"),
        ("diylc.passive.RadialCeramicDiskCapacitor", "value"),
        ("diylc.passive.RadialElectrolytic", "value"),
        ("diylc.passive.AxialFilmCapacitor", "value"),
        ("diylc.passive.AxialElectrolyticCapacitor", "value"),
        ("diylc.passive.TantalumCapacitor", "value"),
        ("diylc.passive.PotentiometerPanel", "resistance"),
        ("diylc.passive.TrimmerPotentiometer", "resistance"),
        ("diylc.passive.ResistorSymbol", "value"),
        ("diylc.passive.CapacitorSymbol", "value"),
        ("diylc.passive.InductorSymbol", "value"),
        ("diylc.passive.FuseSymbol", "value"),
        ("diylc.passive.CrystalOscillator", "value"),
    }

    values: dict[str, Any] = {}
    pts: list[tuple[float, float]] = []
    wire_pts: list[tuple[float, float]] = []
    single_point: tuple[float, float] | None = None

    for child in el:
        tag = child.tag

        # Handle the well-known irregular containers first.
        # v3 XStream sometimes stores points as <java.awt.Point x= y=> instead
        # of <point x= y=>; _point_children catches both.
        if tag in ("points", "controlPoints"):
            pts = [_parse_point(p) for p in _point_children(child)]
            continue
        if tag == "controlPoints2":  # HookupWire and CurvedTrace
            wire_pts = [_parse_point(p) for p in _point_children(child)]
            continue
        if tag in ("point", "java.awt.Point", "controlPoint") and child.get("x") is not None:
            # SolderPad / Label / TraceCut store a bare <point x="" y=""/>;
            # SingleCoilPickup uses the singular <controlPoint x="" y=""/>.
            single_point = _parse_point(child)
            continue
        if tag in ("firstPoint", "secondPoint"):
            # Boards write the corners both inside <controlPoints> AND as
            # standalone first/second points. We trust <controlPoints>.
            continue
        if tag == "name":
            values["name"] = child.text or ""
            continue
        if tag == "value" and "value" in field_names and child.get("unit") is None:
            # Plain string value (resistor models actually use <value
            # value="..." unit="..."/>, those are handled below)
            values["value"] = child.text or ""
            continue
        if tag == "alpha":
            try:
                values["alpha"] = int((child.text or "0").strip())
            except ValueError:
                pass
            continue
        if tag == "text":
            values["text"] = child.text or ""
            continue
        if tag == "font":
            values["font"] = child.get("name", "Tahoma")
            try:
                values["font_size"] = int(child.get("size", "14"))
                values["font_style"] = int(child.get("style", "0"))
            except ValueError:
                pass
            continue

        field_name = _renamed_field(el.tag, tag)

        # Color elements come in two forms: hex="..." attribute (modern)
        # or nested <red>/<green>/<blue>/<alpha> child elements (v3 XStream).
        if "Color" in tag or tag in ("color",) or _looks_like_color(child):
            if field_name in field_names:
                values[field_name] = _parse_color(child)
            continue

        # Measure elements — modern attr form or v3 XStream nested form.
        if _looks_like_measure(child):
            tag_short = el.tag
            if tag_short.startswith("org.diylc.components."):
                tag_short = "diylc." + tag_short[len("org.diylc.components."):]
            m = _parse_measure(child)
            if (tag_short, field_name) in _UNIT_VALUE_AS_STRING:
                # Re-stringify as e.g. "10K", "100nF" — matches the format
                # the original constructor accepts.
                v_str = f"{int(m.value)}" if m.value.is_integer() else f"{m.value:g}"
                values[field_name] = f"{v_str}{m.unit}"
            elif field_name in field_names:
                values[field_name] = m
            continue

        # Booleans, strings, numbers as element text.
        if field_name in field_names:
            text = (child.text or "").strip()
            if not text:
                values[field_name] = ""
            elif text in ("true", "false"):
                values[field_name] = text == "true"
            else:
                # Try int, then leave as string (enum strings stay strings).
                try:
                    values[field_name] = int(text)
                except ValueError:
                    values[field_name] = text

    # Map collected points to the right fields per component class. Normalize
    # both the older `org.diylc.components.*` prefix and any alternate
    # spellings (DIL__IC, TwistedWire) to the canonical class's
    # `__diylc_class__` before dispatching.
    diylc_class = cls.__diylc_class__
    if diylc_class == "diylc.connectivity.HookupWire":
        # v3 sometimes uses <controlPoints> instead of <controlPoints2>; pick
        # whichever bucket actually got populated.
        values["points"] = wire_pts or pts
    elif diylc_class == "diylc.connectivity.CurvedTrace":
        values["points"] = wire_pts or pts
    elif diylc_class == "diylc.connectivity.CopperTrace":
        values["points"] = pts or wire_pts
    elif diylc_class == "diylc.connectivity.SolderPad":
        if single_point is not None:
            values["x"], values["y"] = single_point
        else:
            _set_single_anchor(values, pts)
    elif diylc_class in (
        "diylc.connectivity.TraceCut",
        "diylc.connectivity.Dot",
        "diylc.connectivity.Eyelet",
        "diylc.connectivity.Turret",
    ):
        if single_point is not None:
            values["x"], values["y"] = single_point
        else:
            _set_single_anchor(values, pts)
    elif diylc_class == "diylc.connectivity.Line":
        # Line is a polyline like CopperTrace.
        values["points"] = pts
    elif diylc_class == "diylc.misc.Label":
        if single_point is not None:
            values["x"], values["y"] = single_point
        else:
            _set_single_anchor(values, pts)
    elif diylc_class == "diylc.misc.GroundSymbol":
        if single_point is not None:
            values["x"], values["y"] = single_point
        else:
            _set_single_anchor(values, pts)
    elif diylc_class in ("diylc.misc.Image", "diylc.misc.BOM"):
        if single_point is not None:
            values["x"], values["y"] = single_point
        else:
            _set_single_anchor(values, pts)
    elif diylc_class in (
        "diylc.boards.BlankBoard",
        "diylc.boards.PerfBoard",
        "diylc.boards.VeroBoard",
    ):
        # Boards use corner [p1, p2] in <controlPoints>.
        if pts:
            (values["x1"], values["y1"]) = pts[0]
            (values["x2"], values["y2"]) = pts[1] if len(pts) >= 2 else pts[0]
    elif diylc_class in (
        "diylc.semiconductors.TransistorTO92",
        "diylc.semiconductors.BJTSymbol",
        "diylc.passive.PotentiometerPanel",
        "diylc.passive.TrimmerPotentiometer",
        "diylc.electromechanical.MiniToggleSwitch",
        "diylc.electromechanical.PlasticDCJack",
        "diylc.electromechanical.OpenJack1_4",
        "diylc.boards.TerminalStrip",
        "diylc.tube.TubeSocket",
    ):
        # Single-anchor components — take the first control point.
        _set_single_anchor(values, pts)
    elif diylc_class == "diylc.semiconductors.DIL_IC":
        _set_single_anchor(values, pts)
    elif diylc_class in ("diylc.shapes.Rectangle", "diylc.shapes.Ellipse"):
        # Two-corner shapes — same as boards.
        if pts:
            values["x1"], values["y1"] = pts[0]
            values["x2"], values["y2"] = pts[1] if len(pts) >= 2 else pts[0]
    else:
        # Auto-dispatch by the dataclass's coordinate-field shape. This lets
        # new components Just Work without adding another entry to the table
        # above; the explicit cases above handle the components whose
        # in-XML point ordering doesn't match the naive guess.
        has_xy = "x" in field_names and "y" in field_names
        has_corners = all(k in field_names for k in ("x1", "y1", "x2", "y2"))
        has_points_field = "points" in field_names
        if has_points_field:
            values["points"] = pts
        elif has_corners and len(pts) >= 2:
            values["x1"], values["y1"] = pts[0]
            values["x2"], values["y2"] = pts[1]
        elif has_xy:
            # Prefer the singular <controlPoint x=" y="> when present
            # (SingleCoilPickup etc.); fall back to the first control point.
            if single_point is not None and not pts:
                values["x"], values["y"] = single_point
            else:
                _set_single_anchor(values, pts)
        else:
            # Last-resort: original two-pin behavior.
            _set_two_pin_coords(values, pts)

    # Drop keys the dataclass doesn't accept.
    extra = set(values) - field_names
    for k in extra:
        warnings_out.append(f"{el.tag}: ignoring unknown attribute {k!r}")
        del values[k]

    # Required positional fields that we may have missed (e.g. malformed file).
    missing = [f.name for f in dataclasses.fields(cls)
               if f.default is dataclasses.MISSING
               and f.default_factory is dataclasses.MISSING  # type: ignore[misc]
               and f.name not in values]
    if missing:
        warnings_out.append(
            f"{el.tag}: missing required fields {missing}, skipping"
        )
        return None

    try:
        return cls(**values)
    except (ValueError, TypeError) as exc:
        warnings_out.append(f"{el.tag}: construction failed: {exc}")
        return None


def _resolve_xstream_references(root: ET.Element) -> None:
    """In-place: replace each element with a ``reference="..."`` attribute
    with a deep copy of its referent.

    v3 XStream-serialized files deduplicate identical sub-objects by emitting
    e.g. ``<size reference="../../org.diylc.components.connectivity.SolderPad/size"/>``
    instead of repeating the full ``<size>...</size>`` block. The reference
    path is XPath-ish, evaluated against the element's parent context.

    We do this once up front so the rest of the reader can treat the tree
    as if every reference were inlined.
    """
    import copy as _copy

    # Map child → parent so we can navigate "../" hops.
    parent_map = {c: p for p in root.iter() for c in p}

    def resolve_path(start: ET.Element, ref: str) -> ET.Element | None:
        """Walk an XStream reference path from ``start``."""
        node: ET.Element | None = start
        for part in ref.split("/"):
            if node is None:
                return None
            if part == "..":
                node = parent_map.get(node)
            elif part == "" or part == ".":
                continue
            else:
                # Names may be indexed like "name[2]" (1-based). Strip and use.
                idx = 1
                tag = part
                if "[" in part and part.endswith("]"):
                    tag, _, rest = part.partition("[")
                    try:
                        idx = int(rest[:-1])
                    except ValueError:
                        idx = 1
                # Find the idx-th child with that tag.
                matches = [c for c in node if c.tag == tag]
                if 1 <= idx <= len(matches):
                    node = matches[idx - 1]
                else:
                    return None
        return node

    # Find every reference="..." element and replace it.
    # Walk a snapshot of elements since we mutate the tree.
    refs = [el for el in root.iter() if el.get("reference") is not None]
    # Multiple passes in case references chain.
    for _ in range(5):  # cap to avoid infinite loops on malformed input
        progressed = False
        still_refs: list[ET.Element] = []
        for el in refs:
            ref = el.get("reference")
            if ref is None:
                continue
            parent = parent_map.get(el)
            if parent is None:
                continue
            referent = resolve_path(el, ref)
            if referent is None or referent.get("reference") is not None:
                still_refs.append(el)
                continue
            # Replace el with a deep copy of referent (keeping el's tag so
            # the field-name dispatch in the reader still works).
            clone = _copy.deepcopy(referent)
            clone.tag = el.tag
            # Splice into the parent at el's position.
            idx = list(parent).index(el)
            parent.remove(el)
            parent.insert(idx, clone)
            # Update the parent_map for the new subtree.
            for c in clone.iter():
                for cc in c:
                    parent_map[cc] = c
            parent_map[clone] = parent
            progressed = True
        refs = still_refs
        if not progressed or not refs:
            break


def read_project(path: str | Path) -> Project:
    """Parse a .diy file into a Project."""
    p = Path(path)
    tree = ET.parse(p)
    root = tree.getroot()
    # v1 (DIYLC 1.x/2.x) files use a <Layout> root and a flat, attribute-only
    # element schema (<Resistor X1=.. Y1=.. X2=.. Y2=.. Value=.. Name=..>).
    # Dispatch separately — they share no structure with the modern format.
    if root.tag == "Layout":
        return _read_v1(p, root)
    _resolve_xstream_references(root)
    # Modern files use <project>; older XStream-serialized files use
    # <org.diylc.core.Project>. Accept both.
    if root.tag not in ("project", "org.diylc.core.Project"):
        raise ValueError(f"{p}: expected <project> root, got <{root.tag}>")

    project = Project()
    warnings_out: list[str] = []

    title_el = root.find("title")
    if title_el is not None:
        project.title = title_el.text or ""
    author_el = root.find("author")
    if author_el is not None:
        project.author = author_el.text or ""
    w_el = root.find("width")
    if w_el is not None and w_el.get("value"):
        v = float(w_el.get("value"))
        unit = w_el.get("unit", "cm")
        project.width_cm = v if unit == "cm" else (v * 2.54 if unit == "in" else v / 10.0)
    h_el = root.find("height")
    if h_el is not None and h_el.get("value"):
        v = float(h_el.get("value"))
        unit = h_el.get("unit", "cm")
        project.height_cm = v if unit == "cm" else (v * 2.54 if unit == "in" else v / 10.0)
    g_el = root.find("gridSpacing")
    if g_el is not None and g_el.get("value"):
        v = float(g_el.get("value"))
        unit = g_el.get("unit", "in")
        project.grid_inches = v if unit == "in" else (v / 25.4 if unit == "mm" else v / 2.54)
    fv = root.find("fileVersion")
    if fv is not None:
        try:
            major = int(fv.findtext("major") or "5")
            minor = int(fv.findtext("minor") or "0")
            build = int(fv.findtext("build") or "0")
            project.file_version = (major, minor, build)
        except ValueError:
            pass

    components_el = root.find("components")
    if components_el is not None:
        for el in components_el:
            c = _component_from_element(el, warnings_out)
            if c is not None:
                project.add(c)

    # Stash warnings on the project for callers that want to inspect them.
    # `Project` doesn't have a metadata field, but we attach attribute-style
    # so this stays an opt-in inspection point without changing the dataclass.
    project._read_warnings = warnings_out  # type: ignore[attr-defined]
    if warnings_out:
        warnings.warn(
            f"read_project: {len(warnings_out)} warning(s); see project._read_warnings",
            stacklevel=2,
        )
    return project


def read_warnings(project: Project) -> list[str]:
    """Return the warning list from a previously-read Project."""
    return getattr(project, "_read_warnings", [])


# ---------------------------------------------------------------------------
# v1 reader (DIYLC 1.x / 2.x — <Layout> root, flat attribute-only schema).
# ---------------------------------------------------------------------------

# v1 coordinates are integer perfboard-hole indices. One hole = 0.1 inch on
# both perfboards and stripboards (the only Layout.Type values we see in the
# corpus that have a grid). Convert by multiplying by this constant.
_V1_HOLE_INCHES = 0.1

# Map v1 element tag → builder fn(attrs, name_counter) -> Component | None.
# Defined below, after the helpers.
_V1_BUILDERS: dict[str, Any] = {}


def _v1_xy(attrs: dict[str, str], k1: str = "X1", k2: str = "Y1") -> tuple[float, float]:
    """Read an integer hole index pair from v1 attrs, in inches."""
    x = float(attrs.get(k1, "0")) * _V1_HOLE_INCHES
    y = float(attrs.get(k2, "0")) * _V1_HOLE_INCHES
    return x, y


def _v1_color(name: str) -> str:
    """Convert a v1 color name ('Black', 'Red'...) to a hex string."""
    return {
        "Black": "000000",
        "Red": "ff0000",
        "Blue": "0000ff",
        "Green": "00aa00",
        "Brown": "8b4513",
        "Gray": "808080",
        "Orange": "ff8800",
        "White": "ffffff",
        "Yellow": "ffff00",
    }.get(name, "000000")


def _v1_taper(s: str) -> str:
    """Map v1 'Audio'/'Linear'/'Reverse Audio' → modern LIN/LOG enum."""
    return {
        "Linear": "LIN",
        "Audio": "LOG",
        "Reverse Audio": "REV_LOG",
        "": "LIN",
    }.get(s, "LIN")


def _read_v1(path: Path, root: ET.Element) -> Project:
    """Parse a v1 <Layout> file into a Project.

    v1 files have a flat, attribute-only schema. Coordinates are integer
    perfboard-hole indices; we convert to inches at 0.1 in/hole. An implicit
    board (Perfboard / Stripboard / PCB) of Layout.Width × Layout.Height is
    synthesized as the first component so the user sees the same canvas the
    original layout assumed.

    Unknown elements record a warning and are skipped rather than raising,
    matching the modern reader's tolerance policy.
    """
    from .components import (
        AxialElectrolyticCapacitor, BlankBoard, CopperTrace, DIL_IC, DiodePlastic,
        HookupWire, Jumper, Label, LED, MiniToggleSwitch, OpenJack1_4,
        PerfBoard, PotentiometerPanel, RadialFilmCapacitor, Resistor, SolderPad,
        TraceCut, TransistorTO92, TrimmerPotentiometer, VeroBoard,
    )

    project = Project()
    warnings_out: list[str] = []

    # Project metadata from Layout attrs.
    a = dict(root.attrib)
    project.title = a.get("Project", "")
    # Width/Height are in perfboard holes. Convert to cm via inches.
    try:
        w_holes = float(a.get("Width", "30"))
        h_holes = float(a.get("Height", "20"))
        project.width_cm = (w_holes + 4) * _V1_HOLE_INCHES * 2.54
        project.height_cm = (h_holes + 4) * _V1_HOLE_INCHES * 2.54
    except ValueError:
        pass

    layout_type = a.get("Type", "Perfboard")

    # Synthesize an implicit board sized to the Layout. v1 boards have no
    # explicit element — they're inferred from Layout.Type. Place it inset
    # by 2 holes from each side so wires/pads at the edge stay on-board.
    inset = 2 * _V1_HOLE_INCHES
    try:
        w_holes = float(a.get("Width", "30"))
        h_holes = float(a.get("Height", "20"))
        bx1, by1 = inset, inset
        bx2 = inset + w_holes * _V1_HOLE_INCHES
        by2 = inset + h_holes * _V1_HOLE_INCHES
        if layout_type == "Perfboard":
            project.add(PerfBoard(name="Board", x1=bx1, y1=by1, x2=bx2, y2=by2))
        elif layout_type == "Stripboard":
            project.add(VeroBoard(name="Board", x1=bx1, y1=by1, x2=bx2, y2=by2))
        elif layout_type == "PCB":
            project.add(BlankBoard(name="Board", x1=bx1, y1=by1, x2=bx2, y2=by2))
        # Mono/Stereo layouts have no board (rare; jack-only layouts).
    except (ValueError, TypeError):
        pass

    # Offset every coordinate by the inset so v1's origin-at-corner lines up
    # inside the synthesized board.
    def _xy(attrs, k1="X1", k2="Y1"):
        x, y = _v1_xy(attrs, k1, k2)
        return x + inset, y + inset

    # Track name collisions so two pads with the same auto-name don't clash.
    name_counts: dict[str, int] = {}
    def _uniq(name: str) -> str:
        if not name:
            name = "X"
        if name not in name_counts:
            name_counts[name] = 1
            return name
        name_counts[name] += 1
        return f"{name}_{name_counts[name]}"

    for el in root:
        tag = el.tag
        attrs = dict(el.attrib)
        name = _uniq(attrs.get("Name", ""))
        value = attrs.get("Value", "")
        try:
            if tag == "Pad":
                x, y = _xy(attrs)
                square = attrs.get("Square", "False") == "True"
                color = _v1_color(attrs.get("Color", "Black"))
                project.add(SolderPad(
                    name=name, x=x, y=y, color=color,
                    type="SQUARE" if square else "ROUND",
                ))
            elif tag == "Trace":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(CopperTrace(
                    name=name, points=[(x1, y1), (x2, y2)],
                ))
            elif tag == "Wire":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                color = _v1_color(attrs.get("Color", "Black"))
                project.add(HookupWire(
                    name=name, points=[(x1, y1), (x2, y2)], color=color,
                ))
            elif tag == "Jumper":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(Jumper(name=name, points=[(x1, y1), (x2, y2)]))
            elif tag == "Cut":
                x, y = _xy(attrs)
                project.add(TraceCut(name=name, x=x, y=y))
            elif tag == "Resistor":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(Resistor(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2, value=value,
                ))
            elif tag == "Capacitor":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(RadialFilmCapacitor(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2, value=value,
                ))
            elif tag == "Electrolyte":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(AxialElectrolyticCapacitor(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2, value=value,
                ))
            elif tag == "Diode":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(DiodePlastic(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2, value=value,
                ))
            elif tag == "Led" or tag == "LED":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                project.add(LED(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2, value=value,
                ))
            elif tag == "Transistor":
                x, y = _xy(attrs)
                # v1 Transistor uses a 2-point span (X1,Y1)..(X2,Y2); use
                # the first as the body anchor.
                project.add(TransistorTO92(
                    name=name, x=x, y=y, value=value,
                ))
            elif tag == "IC" or tag == "LineIC":
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                # Pin count = perimeter / 2 (rough — most v1 ICs are DIP8 or
                # DIP14). Default to 8 if math fails.
                w = abs(round((x2 - x1) / _V1_HOLE_INCHES))
                h = abs(round((y2 - y1) / _V1_HOLE_INCHES))
                pins = max(4, min(50, (w + h) * 2))
                pins = pins if pins % 2 == 0 else pins + 1
                project.add(DIL_IC(
                    name=name, x=x1, y=y1, value=value,
                    pin_count=f"_{pins}",
                ))
            elif tag == "Pot":
                x1, y1 = _xy(attrs)
                taper = _v1_taper(attrs.get("Taper", ""))
                project.add(PotentiometerPanel(
                    name=name, x=x1, y=y1, resistance=value or "10K", taper=taper,
                ))
            elif tag == "Trimmer":
                x1, y1 = _xy(attrs)
                project.add(TrimmerPotentiometer(
                    name=name, x=x1, y=y1, resistance=value or "10K",
                ))
            elif tag == "Text":
                x, y = _xy(attrs)
                project.add(Label(
                    name=name, x=x, y=y, text=value,
                ))
            elif tag == "Switch":
                x, y = _xy(attrs)
                # v1 Switch.Value is free text ("DPDT", "On/On"...); the modern
                # MiniToggleSwitch needs a structured enum. Default to DPDT
                # (most-common pedal switch) and keep the original in a Label
                # alongside so the user still sees the v1 spec.
                from .enums import TOGGLE_SWITCH_TYPE
                st = value if value in TOGGLE_SWITCH_TYPE else "DPDT"
                project.add(MiniToggleSwitch(
                    name=name, x=x, y=y, switch_type=st,
                ))
                if value and st != value:
                    project.add(Label(
                        name=_uniq(f"{name}_lbl"),
                        x=x, y=y, text=value,
                    ))
            elif tag == "Jack":
                x, y = _xy(attrs)
                jtype = attrs.get("Type", "Mono").upper()
                project.add(OpenJack1_4(
                    name=name, x=x, y=y,
                    type="STEREO" if jtype == "STEREO" else "MONO",
                ))
            elif tag == "Transformer":
                # No close equivalent in pydiylc yet — render as a labeled
                # rectangle so the position survives the round-trip.
                x1, y1 = _xy(attrs); x2, y2 = _xy(attrs, "X2", "Y2")
                from .components import Rectangle
                project.add(Rectangle(
                    name=name, x1=x1, y1=y1, x2=x2, y2=y2,
                ))
                project.add(Label(
                    name=_uniq("T_label"),
                    x=x1, y=y1, text=value or "Transformer",
                ))
            else:
                warnings_out.append(f"unknown v1 element: {tag}")
        except Exception as exc:
            warnings_out.append(f"v1 {tag} {name}: {type(exc).__name__}: {exc}")

    project._read_warnings = warnings_out  # type: ignore[attr-defined]
    if warnings_out:
        warnings.warn(
            f"read_project (v1): {len(warnings_out)} warning(s); see project._read_warnings",
            stacklevel=2,
        )
    return project
