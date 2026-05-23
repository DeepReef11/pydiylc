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
_TAG_TO_CLASS: dict[str, type[Component]] = {}
for _cls in ALL_COMPONENTS:
    short = _cls.__diylc_class__
    _TAG_TO_CLASS[short] = _cls
    # diylc.connectivity.SolderPad → org.diylc.components.connectivity.SolderPad
    parts = short.split(".")
    if len(parts) >= 3:
        full = ".".join(["org.diylc.components"] + parts[1:])
        _TAG_TO_CLASS[full] = _cls

# A few alternate spellings used by older DIYLC versions that resolve to the
# same Python class as their modern equivalent.
from .components import DIL_IC as _DIL_IC, HookupWire as _HookupWire, OpenJack1_4 as _OpenJack1_4  # noqa: E402

_TAG_TO_CLASS["diylc.semiconductors.DIL__IC"] = _DIL_IC
_TAG_TO_CLASS["org.diylc.components.semiconductors.DIL__IC"] = _DIL_IC
# TwistedWire is a HookupWire variant; we render it as a hookup wire with no
# fidelity loss for the polyline shape (the twist is purely cosmetic).
_TAG_TO_CLASS["diylc.connectivity.TwistedWire"] = _HookupWire
_TAG_TO_CLASS["org.diylc.components.connectivity.TwistedWire"] = _HookupWire
# Older releases wrote OpenJack1_4 as OpenJack1__4 (double underscore).
_TAG_TO_CLASS["diylc.electromechanical.OpenJack1__4"] = _OpenJack1_4
_TAG_TO_CLASS["org.diylc.components.electromechanical.OpenJack1__4"] = _OpenJack1_4

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
    """`<bodyColor hex="abc123"/>` → `'abc123'`."""
    return el.get("hex", "000000")


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
        ("diylc.passive.PotentiometerPanel", "resistance"),
        ("diylc.passive.TrimmerPotentiometer", "resistance"),
        ("diylc.passive.ResistorSymbol", "value"),
        ("diylc.passive.CapacitorSymbol", "value"),
    }

    values: dict[str, Any] = {}
    pts: list[tuple[float, float]] = []
    wire_pts: list[tuple[float, float]] = []
    single_point: tuple[float, float] | None = None

    for child in el:
        tag = child.tag

        # Handle the well-known irregular containers first.
        if tag in ("points", "controlPoints"):
            pts = [_parse_point(p) for p in child.findall("point")]
            continue
        if tag == "controlPoints2":  # HookupWire and CurvedTrace
            wire_pts = [_parse_point(p) for p in child.findall("point")]
            continue
        if tag == "point" and child.get("x") is not None:
            # SolderPad / Label / TraceCut store a bare <point x="" y=""/>
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

        # Color elements have a `hex="..."` attribute.
        if "Color" in tag or tag in ("color",):
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
        values["points"] = wire_pts
    elif diylc_class == "diylc.connectivity.CurvedTrace":
        values["points"] = wire_pts
    elif diylc_class == "diylc.connectivity.CopperTrace":
        values["points"] = pts
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
        # Two-pin: assume [p1, p2, midpoint]
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
