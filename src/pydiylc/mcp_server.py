"""MCP (Model Context Protocol) server for pydiylc.

Exposes pydiylc as a comprehensive tool surface for LLM clients. Workflow:

1. Read ``catalog.json`` (or call ``list_component_types``) once to learn
   the API. Also available as the ``pydiylc://catalog`` MCP resource.
2. Build a layout with ``create_project`` + ``add_component`` or one-shot
   ``create_project_from_dict``.
3. Edit iteratively: ``move_component``, ``rotate_component``,
   ``duplicate_component``, ``set_value``, ``remove_component``.
4. Save / render with ``save``, ``render_svg``, ``render_png``, ``to_json``.

The server also exposes MCP **resources** (catalog + LLMS guide) and
**prompts** (canned multi-step instructions for common workflows).

Run::

    pip install pydiylc[mcp]
    pydiylc-mcp                 # stdio transport (the MCP default)

The MCP SDK is an optional dependency. Importing this module without it
raises ImportError with an install hint.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .core import Project
from .catalog import build_catalog
from .loader import project_from_dict, component_from_dict
from .reader import read_project, read_warnings


def _require_mcp():
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "pydiylc.mcp_server requires the MCP SDK.\n"
            "  pip install pydiylc[mcp]\n"
            "  (or: pip install 'mcp[cli]')"
        ) from exc


def has_mcp() -> bool:
    try:
        _require_mcp()
        return True
    except ImportError:
        return False


# In-memory project store. Keyed by string id chosen by the client (defaulting
# to "default"). Multiple parallel projects are supported.
_PROJECTS: dict[str, Project] = {}


def _get(project_id: str) -> Project:
    if project_id not in _PROJECTS:
        raise KeyError(
            f"no project with id {project_id!r}; call create_project first"
        )
    return _PROJECTS[project_id]


def _find_component(p: Project, name: str):
    """Locate (index, component) by name. Raises KeyError on miss."""
    for i, c in enumerate(p.components):
        if getattr(c, "name", None) == name:
            return i, c
    raise KeyError(f"no component named {name!r}")


def _component_summary(comp, index: int) -> dict:
    """Short JSON-friendly view of a component for tool returns."""
    from .core import Measure
    info: dict = {
        "index": index,
        "type": type(comp).__name__,
        "name": getattr(comp, "name", None),
    }
    # Surface anchor + the primary value-like field when present.
    if hasattr(comp, "x1") and hasattr(comp, "x2"):
        info["x1"] = comp.x1; info["y1"] = comp.y1
        info["x2"] = comp.x2; info["y2"] = comp.y2
    elif hasattr(comp, "points"):
        info["points"] = [list(p) for p in comp.points]
    elif hasattr(comp, "x") and hasattr(comp, "y"):
        info["x"] = comp.x; info["y"] = comp.y
    for k in ("value", "text", "resistance", "tube_type", "orientation"):
        if hasattr(comp, k):
            v = getattr(comp, k)
            if v not in (None, ""):
                info[k] = v
    return info


def build_server():
    """Construct the FastMCP app. Separate function so tests can poke it."""
    _require_mcp()
    from mcp.server.fastmcp import FastMCP
    from . import moves
    from . import tree_editor
    from .catalog import bundled_catalog_path, bundled_llms_txt_path

    server = FastMCP(name="pydiylc")

    # =====================================================================
    # Catalog & reference
    # =====================================================================

    @server.tool()
    def list_component_types() -> dict:
        """Return the full catalog: every component, its fields, defaults, enum
        choices. Also available as the ``pydiylc://catalog`` resource."""
        return build_catalog()

    @server.tool()
    def enum_values(enum_name: str) -> list[str]:
        """List the allowed values for a named enum pool (e.g. 'POWER',
        'VOLTAGE', 'TRANSISTOR_PINOUT'). Helpful when you need to set a
        field that has an enum constraint without grepping the catalog."""
        from . import enums

        v = getattr(enums, enum_name, None)
        if not isinstance(v, tuple):
            raise KeyError(
                f"no enum {enum_name!r}; see catalog.enum_pool for the list"
            )
        return list(v)

    @server.tool()
    def describe_component_type(type_name: str) -> dict:
        """Return the catalog entry for a single component type."""
        cat = build_catalog()
        for entry in cat["components"]:
            if entry["python_class"] == type_name:
                return entry
        raise KeyError(
            f"no component type {type_name!r}; "
            "see list_component_types for the full list"
        )

    # =====================================================================
    # Project lifecycle
    # =====================================================================

    @server.tool()
    def create_project(
        project_id: str = "default",
        title: str = "New Project",
        width_cm: float = 29.0,
        height_cm: float = 21.0,
    ) -> dict:
        """Create a new empty project at ``project_id`` (default 'default').
        If one already exists at that id, it's replaced."""
        p = Project(title=title, width_cm=width_cm, height_cm=height_cm)
        _PROJECTS[project_id] = p
        return {"project_id": project_id, "title": p.title, "components": 0}

    @server.tool()
    def create_project_from_dict(payload: dict, project_id: str = "default") -> dict:
        """Build a Project from a JSON-loader dict in one call.

        The dict format mirrors the catalog: a top-level object with ``title``,
        ``width_cm``, ``height_cm``, and a ``components`` list. Each component
        entry has a ``type`` (or ``_type``) field naming a pydiylc class plus
        the constructor kwargs. See LLMS.txt for the full spec."""
        p = project_from_dict(payload)
        _PROJECTS[project_id] = p
        return {
            "project_id": project_id,
            "title": p.title,
            "components": len(p.components),
        }

    @server.tool()
    def list_projects() -> list[dict]:
        """All projects currently in the server's memory."""
        return [
            {
                "project_id": pid,
                "title": p.title,
                "components": len(p.components),
                "width_cm": p.width_cm,
                "height_cm": p.height_cm,
            }
            for pid, p in _PROJECTS.items()
        ]

    @server.tool()
    def delete_project(project_id: str = "default") -> dict:
        """Drop a project from the in-memory store."""
        existed = _PROJECTS.pop(project_id, None) is not None
        return {"project_id": project_id, "deleted": existed}

    @server.tool()
    def set_project_metadata(
        project_id: str = "default",
        title: str | None = None,
        author: str | None = None,
        width_cm: float | None = None,
        height_cm: float | None = None,
    ) -> dict:
        """Update project-level fields (title / author / canvas size)."""
        p = _get(project_id)
        if title is not None: p.title = title
        if author is not None: p.author = author
        if width_cm is not None: p.width_cm = float(width_cm)
        if height_cm is not None: p.height_cm = float(height_cm)
        return {
            "project_id": project_id,
            "title": p.title,
            "author": p.author,
            "width_cm": p.width_cm,
            "height_cm": p.height_cm,
        }

    # =====================================================================
    # Component inspection
    # =====================================================================

    @server.tool()
    def list_components(project_id: str = "default") -> list[dict]:
        """List every component in the project, with anchor coords + value."""
        p = _get(project_id)
        return [_component_summary(c, i) for i, c in enumerate(p.components)]

    @server.tool()
    def get_component(name: str, project_id: str = "default") -> dict:
        """Return the full field dict of one component by name."""
        from .cli import _component_to_dict

        p = _get(project_id)
        _i, c = _find_component(p, name)
        return _component_to_dict(c)

    @server.tool()
    def find_components(
        query: str, project_id: str = "default", limit: int = 20
    ) -> list[dict]:
        """Fuzzy-search components in the project (name + type). Returns the
        same shape as list_components, sorted best-match first.

        Uses the same fzf-style subsequence matcher the GUI's `/` and `g`
        menus use, so 'r3' finds 'R3', 'r3end2' finds 'R3 end 2', etc."""
        from .jump import searchable_targets, fuzzy_filter

        p = _get(project_id)
        targets = searchable_targets(p)
        matches = fuzzy_filter(targets, query)[:limit]
        out: list[dict] = []
        seen_idx: set[int] = set()
        for t in matches:
            if t.component_index in seen_idx:
                continue
            seen_idx.add(t.component_index)
            out.append(_component_summary(p.components[t.component_index], t.component_index))
        return out

    # =====================================================================
    # Component edits (mirror the viewer's actions)
    # =====================================================================

    @server.tool()
    def add_component(component: dict, project_id: str = "default") -> dict:
        """Add a component. ``component`` is the JSON-loader form (a dict
        with ``type`` plus kwargs). Returns a component summary."""
        p = _get(project_id)
        c = component_from_dict(component)
        p.add(c)
        return _component_summary(c, len(p.components) - 1)

    @server.tool()
    def remove_component(name: str, project_id: str = "default") -> dict:
        """Remove the first component matching ``name``."""
        p = _get(project_id)
        try:
            i, _c = _find_component(p, name)
        except KeyError:
            return {"removed": False, "remaining": len(p.components)}
        del p.components[i]
        return {"removed": True, "remaining": len(p.components)}

    @server.tool()
    def move_component(
        name: str,
        dx: float,
        dy: float,
        project_id: str = "default",
    ) -> dict:
        """Translate a component by (dx, dy) inches, propagating per the
        connection-aware rules: moving a board drags components mounted on
        it; wire endpoints coincident with the moved part follow it (the
        wire's far end stays put, so leads stretch)."""
        p = _get(project_id)
        i, _c = _find_component(p, name)
        moves.move_component(p, i, dx, dy)
        return _component_summary(p.components[i], i)

    @server.tool()
    def move_node(
        name: str,
        point_index: int,
        dx: float,
        dy: float,
        project_id: str = "default",
    ) -> dict:
        """Move a single control point of a component by (dx, dy). Unlike
        move_component, this does NOT pull coincident points on other
        components along — use it to deliberately detach a connection."""
        p = _get(project_id)
        i, _c = _find_component(p, name)
        moves.move_node(p, i, point_index, dx, dy)
        return _component_summary(p.components[i], i)

    @server.tool()
    def move_node_to(
        name: str,
        point_index: int,
        x: float,
        y: float,
        project_id: str = "default",
    ) -> dict:
        """Move a control point to an absolute (x, y) — used for snap-to-target
        operations (place this pin on top of that pin)."""
        p = _get(project_id)
        i, _c = _find_component(p, name)
        moves.move_node_to(p, i, point_index, x, y)
        return _component_summary(p.components[i], i)

    @server.tool()
    def rotate_component(
        name: str,
        clockwise: bool = True,
        project_id: str = "default",
    ) -> dict:
        """Rotate a component 90°. Components with an ``orientation`` enum
        cycle the enum (so derived pins re-orient cleanly); two-pin and
        points-list components rotate their coordinates about the centroid."""
        p = _get(project_id)
        i, _c = _find_component(p, name)
        moves.rotate_component(p, i, clockwise=clockwise)
        return _component_summary(p.components[i], i)

    @server.tool()
    def duplicate_component(
        name: str,
        new_name: str | None = None,
        dx: float = 0.3,
        dy: float = 0.0,
        project_id: str = "default",
    ) -> dict:
        """Clone the named component, offset by (dx, dy) inches with an
        auto-incremented name (or the explicit ``new_name`` if given)."""
        p = _get(project_id)
        _i, original = _find_component(p, name)
        existing = {getattr(c, "name", None) for c in p.components}
        existing.discard(None)
        target_name = new_name or tree_editor.increment_name(
            existing, getattr(original, "name", "X")
        )
        clone = tree_editor.duplicate_component(
            original, target_name, dx=dx, dy=dy
        )
        p.add(clone)
        return _component_summary(clone, len(p.components) - 1)

    @server.tool()
    def set_value(
        name: str,
        value: str,
        field: str | None = None,
        project_id: str = "default",
    ) -> dict:
        """Update a component's primary value field. By default we pick the
        field automatically (``value`` for resistors/caps/etc., ``text`` for
        labels, ``resistance`` for pots, ``tube_type`` for tubes) but
        ``field`` can pin it explicitly."""
        p = _get(project_id)
        _i, c = _find_component(p, name)
        target = field or tree_editor.primary_value_field(c)
        if target is None:
            raise ValueError(
                f"{type(c).__name__} has no editable value field; "
                "pass 'field' explicitly."
            )
        if not hasattr(c, target):
            raise ValueError(f"{type(c).__name__} has no field {target!r}")
        setattr(c, target, value)
        return _component_summary(c, _i)

    @server.tool()
    def add_wire(
        src: list[float],
        dst: list[float],
        name: str | None = None,
        color: str = "000000",
        project_id: str = "default",
    ) -> dict:
        """Add a HookupWire from src=(x, y) to dst=(x, y). Auto-names if no
        ``name`` is given."""
        from .components import HookupWire

        p = _get(project_id)
        if len(src) != 2 or len(dst) != 2:
            raise ValueError("src and dst must each be [x, y]")
        existing = {getattr(c, "name", None) for c in p.components}
        if name is None:
            i = 1
            while f"HookupWire{i}" in existing:
                i += 1
            name = f"HookupWire{i}"
        wire = HookupWire(name=name, points=[tuple(src), tuple(dst)], color=color)
        p.add(wire)
        return _component_summary(wire, len(p.components) - 1)

    # =====================================================================
    # Save / render / read
    # =====================================================================

    @server.tool()
    def save(path: str, project_id: str = "default") -> dict:
        """Save the project to a `.diy` file. Returns the absolute path."""
        p = _get(project_id)
        out = p.save(path)
        return {"path": str(Path(out).resolve()), "components": len(p.components)}

    @server.tool()
    def render_svg(path: str, project_id: str = "default", dpi: int = 96) -> dict:
        """Render the project to an SVG preview file."""
        from .svg import render_svg as _render_svg, RenderOptions

        p = _get(project_id)
        out = Path(path)
        out.write_text(_render_svg(p, RenderOptions(px_per_inch=dpi)), encoding="utf-8")
        return {"path": str(out.resolve())}

    @server.tool()
    def render_png(path: str, project_id: str = "default", dpi: int = 96) -> dict:
        """Render the project to a PNG file. Requires pycairo on the server
        side (install with ``pip install pydiylc[viewer]``). Errors raise
        ImportError if it isn't available."""
        from .cairo_render import render_png as _render_png

        p = _get(project_id)
        _render_png(p, path, dpi=dpi)
        return {"path": str(Path(path).resolve())}

    @server.tool()
    def to_json(project_id: str = "default") -> dict:
        """Serialize the project to a round-trip-clean JSON document."""
        from .cli import _component_to_dict

        p = _get(project_id)
        return {
            "title": p.title,
            "author": p.author,
            "width_cm": p.width_cm,
            "height_cm": p.height_cm,
            "components": [_component_to_dict(c) for c in p.components],
        }

    @server.tool()
    def read_diy(path: str, project_id: str = "default") -> dict:
        """Parse a .diy file from disk into a project slot. Unknown component
        types are skipped with warnings (returned in the response)."""
        p = read_project(path)
        _PROJECTS[project_id] = p
        return {
            "project_id": project_id,
            "title": p.title,
            "components": len(p.components),
            "warnings": read_warnings(p),
        }

    # =====================================================================
    # Resources (read-only data the client can subscribe to)
    # =====================================================================

    @server.resource("pydiylc://catalog")
    def catalog_resource() -> str:
        """The full component catalog as JSON. Equivalent to
        list_component_types(), but exposed as a resource URI so clients can
        cache or reference it without invoking a tool."""
        path = bundled_catalog_path()
        if path is not None and path.exists():
            return path.read_text(encoding="utf-8")
        return json.dumps(build_catalog(), indent=2)

    @server.resource("pydiylc://llms.txt")
    def llms_resource() -> str:
        """The LLMS.txt guide — flat-markdown overview meant to be fed to
        a coding assistant. Lists every component, enum, and the JSON
        schema for ``create_project_from_dict``."""
        path = bundled_llms_txt_path()
        if path is not None and path.exists():
            return path.read_text(encoding="utf-8")
        return "(LLMS.txt not bundled in this installation)"

    # =====================================================================
    # Prompts (canned workflows)
    # =====================================================================

    @server.prompt()
    def build_pedal_layout(name: str = "MyBooster") -> str:
        """Walkthrough for building a guitar-pedal layout from scratch."""
        return (
            f"Build a small guitar effects pedal layout called {name!r}.\n\n"
            "1. Call `list_component_types` (or read the `pydiylc://catalog` "
            "resource) to see available components.\n"
            "2. `create_project(project_id='pedal', title='" + name + "', "
            "width_cm=18, height_cm=10)`.\n"
            "3. Add a VeroBoard around (1, 1) → (2.2, 1.7) as the stripboard.\n"
            "4. Add the active component (TransistorTO92 or DIL_IC), the "
            "passives (Resistor / RadialFilmCapacitor / RadialElectrolytic), "
            "a PotentiometerPanel for volume, jacks (OpenJack1_4, "
            "PlasticDCJack), and a MiniToggleSwitch with switch_type='_3PDT' "
            "for true bypass.\n"
            "5. Connect them with `add_wire` calls or HookupWire components.\n"
            "6. `render_svg('preview.svg')` to preview, then "
            "`save('layout.diy')` to emit the DIYLC file.\n\n"
            "For each component use sensible keyword args (every position "
            "should be on the 0.1 in grid). The catalog lists which fields "
            "are required vs. defaulted."
        )

    @server.prompt()
    def modify_existing_layout(diy_path: str = "input.diy") -> str:
        """Walkthrough for reading an existing layout and making edits."""
        return (
            f"Read the existing layout at {diy_path!r} and tweak it.\n\n"
            f"1. `read_diy(path={diy_path!r}, project_id='layout')` to load.\n"
            "2. `list_components` to see what's there.\n"
            "3. Use `find_components('R3')` (fuzzy) to locate components by "
            "name fragment.\n"
            "4. Apply edits: `move_component`, `rotate_component`, "
            "`set_value`, `duplicate_component`, `remove_component`.\n"
            "5. `to_json` to inspect the final state, or `save` to write "
            "a new .diy.\n\n"
            "Connection-aware moves: `move_component` drags wires that "
            "touch the part along; `move_node` deliberately detaches a "
            "single control point from its junction."
        )

    return server


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point. Runs the server on stdio."""
    try:
        server = build_server()
    except ImportError as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 2
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
