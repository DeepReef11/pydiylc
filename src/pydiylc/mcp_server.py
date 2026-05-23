"""MCP (Model Context Protocol) server for pydiylc.

Exposes pydiylc as a comprehensive tool surface for LLM clients. Workflow:

1. Read ``catalog.json`` (or call ``list_component_types``) once to learn
   the API. Also available as the ``pydiylc://catalog`` MCP resource.
2. Build a layout with ``create_project`` + ``add_components`` (batch) or
   the one-shot ``create_project_from_dict``.
3. Wire it up with ``connect`` (by component name + pin index) — the
   nearest pin pair is chosen automatically when indices are omitted.
4. Edit iteratively: ``move_component``, ``rotate_component``,
   ``duplicate_component``, ``set_value`` / ``set_field``, ``remove_component``.
5. ``validate`` to catch duplicate names / off-canvas geometry before save.
6. Save / render with ``save``, ``render_svg``, ``render_png``, ``to_json``.
   All four accept ``return_content=True`` for inline content (no disk I/O).

Mistakes are recoverable: every mutating tool snapshots the project, so
``undo`` / ``redo`` work the same as in the GUI viewer. Use ``history``
to inspect the stack.

Errors include 'did you mean X?' hints for both component names and
project ids — useful when an LLM has typo'd a name three calls into a
multi-step edit.

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

# Undo/redo history per project. Populated lazily on first mutating tool call.
# Each entry mirrors the viewer's session-level history so an LLM can undo
# bad edits without needing to redo work from scratch.
_HISTORIES: dict[str, "object"] = {}  # value is history.History


def _get(project_id: str) -> Project:
    if project_id not in _PROJECTS:
        # Suggest the closest existing project id when there's a near miss —
        # makes typos in long sessions self-correcting.
        suggestions = _close_matches(project_id, list(_PROJECTS.keys()), n=3)
        hint = (
            f"; did you mean {', '.join(repr(s) for s in suggestions)}?"
            if suggestions
            else "; call create_project first"
        )
        raise KeyError(f"no project with id {project_id!r}{hint}")
    return _PROJECTS[project_id]


def _close_matches(needle: str, haystack: list[str], n: int = 3) -> list[str]:
    """Return up to ``n`` closest matches from ``haystack``.

    Used to produce 'did you mean X?' hints in KeyError messages — much more
    useful than a bare 'not found' when an LLM mistypes a name three calls
    into a multi-step edit.
    """
    import difflib

    return difflib.get_close_matches(needle, haystack, n=n, cutoff=0.5)


def _history_for(project_id: str):
    """Lazily build (and cache) the History stack for a project."""
    from .history import History

    h = _HISTORIES.get(project_id)
    if h is None:
        p = _get(project_id)
        h = History(project=p)
        _HISTORIES[project_id] = h
    return h


def _record_history(project_id: str, label: str) -> None:
    """Snapshot the project before a mutating tool call.

    Failures here are swallowed — undo is a convenience, not a hard
    invariant; never block an edit on a snapshot error.
    """
    try:
        _history_for(project_id).record(label)
    except Exception:
        pass


def _find_component(p: Project, name: str):
    """Locate (index, component) by name. Raises KeyError on miss.

    The error message lists the closest-matching existing names — vital
    when the LLM has guessed a name and needs to recover from the typo.
    """
    for i, c in enumerate(p.components):
        if getattr(c, "name", None) == name:
            return i, c
    names = [getattr(c, "name", None) for c in p.components]
    names = [n for n in names if n]
    suggestions = _close_matches(name, names)
    if suggestions:
        hint = f"; did you mean {', '.join(repr(s) for s in suggestions)}?"
    else:
        hint = "; try list_components or find_components for the full list"
    raise KeyError(f"no component named {name!r}{hint}")


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
        # 'did you mean' fallback so LLMs can self-correct guesses.
        names = [e["python_class"] for e in cat["components"]]
        sugg = _close_matches(type_name, names)
        hint = (
            f"; did you mean {', '.join(repr(s) for s in sugg)}?"
            if sugg
            else "; see list_component_types for the full list"
        )
        raise KeyError(f"no component type {type_name!r}{hint}")

    @server.tool()
    def list_categories() -> list[dict]:
        """List component categories (passive, semiconductors, boards, etc.).

        Cheap discovery path that avoids fetching the full catalog when an
        LLM just wants "show me the tube components". Each entry has a
        ``category`` slug and the ``count`` of components in it. Categories
        come from the DIYLC class path (``diylc.passive.Resistor`` →
        passive)."""
        from collections import Counter
        cat = build_catalog()
        counts: Counter[str] = Counter()
        for e in cat["components"]:
            parts = e["diylc_class"].split(".")
            category = parts[1] if len(parts) >= 3 else "misc"
            counts[category] += 1
        return [
            {"category": name, "count": n}
            for name, n in sorted(counts.items())
        ]

    @server.tool()
    def list_components_in_category(category: str) -> list[dict]:
        """List every component in a given category (e.g. 'passive', 'tube').

        Returns ``[{python_class, diylc_class, doc_first_line}, ...]``.
        Pair with ``describe_component_type`` for full field info on a pick.
        """
        cat = build_catalog()
        out: list[dict] = []
        for e in cat["components"]:
            parts = e["diylc_class"].split(".")
            if len(parts) >= 3 and parts[1] == category:
                out.append({
                    "python_class": e["python_class"],
                    "diylc_class": e["diylc_class"],
                    "doc_first_line": (e["doc"] or "").split("\n", 1)[0],
                })
        if not out:
            cats = sorted({e["diylc_class"].split(".")[1]
                           for e in cat["components"]
                           if len(e["diylc_class"].split(".")) >= 3})
            sugg = _close_matches(category, cats)
            hint = (
                f"; did you mean {', '.join(repr(s) for s in sugg)}?"
                if sugg
                else f"; valid categories: {cats}"
            )
            raise KeyError(f"no category {category!r}{hint}")
        return out

    @server.tool()
    def list_enums() -> list[dict]:
        """List every enum the catalog references.

        Companion to ``enum_values``: instead of needing to already know an
        enum exists, an LLM can discover them. Each entry has ``name`` and
        ``count`` (how many allowed values). Use ``enum_values`` to fetch
        the values for one."""
        cat = build_catalog()
        pool = cat.get("enum_pool", {})
        return [
            {"name": name, "count": len(values)}
            for name, values in sorted(pool.items())
        ]

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
        _HISTORIES.pop(project_id, None)
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
        _HISTORIES.pop(project_id, None)
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
        _HISTORIES.pop(project_id, None)
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
        _record_history(project_id, "set metadata")
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
    def add_component(
        component: dict,
        project_id: str = "default",
        dry_run: bool = False,
    ) -> dict:
        """Add a component. ``component`` is the JSON-loader form (a dict
        with ``type`` plus kwargs). Returns a component summary.

        ``dry_run=True`` validates the component without adding it — useful
        when you want to surface enum / type errors to the user before
        committing the edit."""
        p = _get(project_id)
        # component_from_dict raises ValueError for bad types/enums; that
        # surfaces straight to the client as a ToolError.
        c = component_from_dict(component)
        if dry_run:
            return {
                "dry_run": True,
                "preview": _component_summary(c, len(p.components)),
            }
        _record_history(project_id, f"add {type(c).__name__}")
        p.add(c)
        return _component_summary(c, len(p.components) - 1)

    @server.tool()
    def add_components(
        components: list[dict],
        project_id: str = "default",
        stop_on_error: bool = False,
    ) -> dict:
        """Add many components in one call. Returns per-item results.

        Each input dict is the same shape `add_component` takes. When an
        item fails validation, the error message is recorded in the
        ``errors`` list and (by default) the batch continues — set
        ``stop_on_error=True`` to abort the whole batch on the first
        failure (no partial commit; the project is left unchanged).

        This compresses what would otherwise be N round-trips into one,
        which matters a lot for LLM-driven workflows that often add 20-50
        components to build a pedal layout."""
        p = _get(project_id)
        # Build all components first so we can roll back on stop_on_error.
        built: list = []
        errors: list[dict] = []
        for i, item in enumerate(components):
            try:
                built.append(component_from_dict(item))
            except Exception as exc:
                errors.append({
                    "index": i,
                    "name": item.get("name"),
                    "type": item.get("type") or item.get("_type"),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                if stop_on_error:
                    return {
                        "added": 0,
                        "errors": errors,
                        "aborted": True,
                    }
                built.append(None)

        _record_history(project_id, f"add {len(components)} components")
        added: list[dict] = []
        for c in built:
            if c is None:
                continue
            p.add(c)
            added.append(_component_summary(c, len(p.components) - 1))
        return {
            "added": len(added),
            "components": added,
            "errors": errors,
            "aborted": False,
        }

    @server.tool()
    def remove_component(name: str, project_id: str = "default") -> dict:
        """Remove the first component matching ``name``."""
        p = _get(project_id)
        try:
            i, _c = _find_component(p, name)
        except KeyError:
            return {"removed": False, "remaining": len(p.components)}
        _record_history(project_id, f"remove {name}")
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
        _record_history(project_id, f"move {name}")
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
        _record_history(project_id, f"move node {name}.{point_index}")
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
        _record_history(project_id, f"snap node {name}.{point_index}")
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
        _record_history(project_id, f"rotate {name}")
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
        _record_history(project_id, f"duplicate {name}")
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
        _record_history(project_id, f"set {name}.{target}")
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
        _record_history(project_id, f"add wire {name}")
        wire = HookupWire(name=name, points=[tuple(src), tuple(dst)], color=color)
        p.add(wire)
        return _component_summary(wire, len(p.components) - 1)

    @server.tool()
    def connect(
        from_name: str,
        to_name: str,
        from_pin: int | None = None,
        to_pin: int | None = None,
        kind: str = "wire",
        color: str = "000000",
        name: str | None = None,
        project_id: str = "default",
    ) -> dict:
        """Wire two named components together by control-point index.

        Most natural way to express "connect R1 to C2" without first
        looking up coordinates: pick a pin on each component (or omit and
        we'll pick the nearest pair) and we add a HookupWire (default)
        or a CopperTrace between them.

        ``kind`` is one of ``'wire'`` (HookupWire) or ``'trace'``
        (CopperTrace). ``from_pin`` / ``to_pin`` are control-point
        indices (see ``get_pins``); if omitted, the closest pair between
        the two components is chosen automatically.
        """
        from .components import HookupWire, CopperTrace
        from .graph import control_points_of

        if kind not in ("wire", "trace"):
            raise ValueError(f"kind must be 'wire' or 'trace', got {kind!r}")

        p = _get(project_id)
        i_from, c_from = _find_component(p, from_name)
        i_to, c_to = _find_component(p, to_name)

        cps_from = control_points_of(c_from, i_from)
        cps_to = control_points_of(c_to, i_to)
        if not cps_from or not cps_to:
            raise ValueError(
                f"can't connect: {from_name if not cps_from else to_name!r} "
                f"has no addressable pins"
            )

        # Pick endpoints. Explicit pin index wins; otherwise the closest pair.
        def _by_index(cps, idx):
            for cp in cps:
                if cp.point_index == idx:
                    return cp
            raise ValueError(
                f"pin index {idx} out of range; "
                f"{[cp.point_index for cp in cps]} are valid"
            )

        if from_pin is not None and to_pin is not None:
            a = _by_index(cps_from, from_pin)
            b = _by_index(cps_to, to_pin)
        else:
            best = None
            for af in cps_from:
                for bt in cps_to:
                    d2 = (af.x - bt.x) ** 2 + (af.y - bt.y) ** 2
                    if best is None or d2 < best[0]:
                        best = (d2, af, bt)
            assert best is not None
            a, b = best[1], best[2]

        # Auto-name based on kind, avoiding collisions.
        existing = {getattr(c, "name", None) for c in p.components}
        if name is None:
            prefix = "W" if kind == "wire" else "T"
            i = 1
            while f"{prefix}{i}" in existing:
                i += 1
            name = f"{prefix}{i}"

        _record_history(project_id, f"connect {from_name}→{to_name}")
        if kind == "wire":
            comp = HookupWire(name=name, points=[(a.x, a.y), (b.x, b.y)], color=color)
        else:
            comp = CopperTrace(name=name, points=[(a.x, a.y), (b.x, b.y)])
        p.add(comp)
        return {
            **_component_summary(comp, len(p.components) - 1),
            "from": {"name": from_name, "pin": a.point_index},
            "to": {"name": to_name, "pin": b.point_index},
        }

    @server.tool()
    def get_pins(name: str, project_id: str = "default") -> list[dict]:
        """List every addressable pin / control-point on a component.

        Returns ``[{pin: int, label: str, x: float, y: float}, ...]``.
        Pair this with ``connect`` to wire by pin index, or with
        ``move_node`` / ``move_node_to`` to nudge a single endpoint.
        """
        p = _get(project_id)
        _i, c = _find_component(p, name)
        pins = tree_editor.addable_pins(c)
        return [
            {"pin": idx, "label": label, "x": x, "y": y}
            for (idx, label, x, y) in pins
        ]

    @server.tool()
    def set_field(
        name: str,
        field: str,
        value,
        project_id: str = "default",
        dry_run: bool = False,
    ) -> dict:
        """Set any dataclass field on a component (orientation, alpha,
        body_color, ...).

        Coerces ``value`` to the field's annotated type when it's a
        primitive (int, float, bool, str). For Measure-typed fields, pass
        a dict ``{"value": ..., "unit": ...}``. For enum-constrained
        fields, the underlying validator runs on commit and raises with
        the allowed values.

        ``dry_run=True`` reports what the coercion would do without
        actually writing.
        """
        import dataclasses
        from .core import Measure

        p = _get(project_id)
        i, c = _find_component(p, name)
        fields = {f.name: f for f in dataclasses.fields(type(c))}
        if field not in fields:
            allowed = sorted(fields)
            sugg = _close_matches(field, allowed)
            hint = (
                f"; did you mean {', '.join(repr(s) for s in sugg)}?"
                if sugg
                else f"; valid fields: {allowed}"
            )
            raise ValueError(f"{type(c).__name__} has no field {field!r}{hint}")

        f = fields[field]
        # Type coercion. We only special-case the simple cases — anything
        # exotic (Sequence[Point], etc.) should be set via the dedicated
        # move_* / add_component tools instead.
        ann = f.type
        if isinstance(ann, type) and ann is Measure and isinstance(value, dict):
            coerced = Measure(value=float(value.get("value", 0)),
                              unit=str(value.get("unit", "in")))
        elif isinstance(ann, type) and ann in (int, float, bool, str):
            coerced = ann(value)
        else:
            coerced = value

        if dry_run:
            return {
                "dry_run": True,
                "field": field,
                "from": getattr(c, field),
                "to": coerced,
            }

        _record_history(project_id, f"set {name}.{field}")
        # Re-validate enums by going through __post_init__ via a fresh
        # dataclasses.replace. If the value is invalid, this raises before
        # we mutate the live component.
        try:
            updated = dataclasses.replace(c, **{field: coerced})
        except Exception as exc:
            raise ValueError(
                f"set_field {field}={coerced!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        # Replace the component in place to preserve list ordering.
        p.components[i] = updated
        return _component_summary(updated, i)

    @server.tool()
    def set_fields(
        name: str,
        fields: dict,
        project_id: str = "default",
        dry_run: bool = False,
    ) -> dict:
        """Set multiple fields on one component in a single call.

        Equivalent to N ``set_field`` calls but cheaper for LLM workflows
        that often want to tweak ``alpha``, ``orientation``, and a color
        together. Uses ``dataclasses.replace`` so enum validation runs
        once on the final state — either all the changes commit or none
        do.

        ``fields`` is a dict ``{"field_name": new_value, ...}``.
        Measure-typed fields take ``{"value": ..., "unit": ...}``.
        """
        import dataclasses
        from .core import Measure

        p = _get(project_id)
        i, c = _find_component(p, name)
        spec = {f.name: f for f in dataclasses.fields(type(c))}

        coerced: dict = {}
        for fname, val in fields.items():
            if fname not in spec:
                allowed = sorted(spec)
                sugg = _close_matches(fname, allowed)
                hint = (
                    f"; did you mean {', '.join(repr(s) for s in sugg)}?"
                    if sugg
                    else f"; valid fields: {allowed}"
                )
                raise ValueError(
                    f"{type(c).__name__} has no field {fname!r}{hint}"
                )
            ann = spec[fname].type
            if isinstance(ann, type) and ann is Measure and isinstance(val, dict):
                coerced[fname] = Measure(
                    value=float(val.get("value", 0)),
                    unit=str(val.get("unit", "in")),
                )
            elif isinstance(ann, type) and ann in (int, float, bool, str):
                coerced[fname] = ann(val)
            else:
                coerced[fname] = val

        if dry_run:
            return {
                "dry_run": True,
                "changes": {
                    k: {"from": getattr(c, k), "to": coerced[k]}
                    for k in coerced
                },
            }

        _record_history(project_id, f"set {name} ({len(coerced)} fields)")
        try:
            updated = dataclasses.replace(c, **coerced)
        except Exception as exc:
            raise ValueError(
                f"set_fields: {type(exc).__name__}: {exc}"
            ) from exc
        p.components[i] = updated
        return _component_summary(updated, i)

    @server.tool()
    def snap_to_grid(
        name: str | None = None,
        project_id: str = "default",
        grid: float = 0.1,
        dry_run: bool = False,
    ) -> dict:
        """Snap a component's control points (or every component's) to the
        nearest grid intersection.

        Default grid is 0.1 in (DIYLC's standard). Without ``name`` this
        snaps every component in the project — useful for cleaning up a
        layout where the LLM picked coordinates with too much precision
        ('2.4455400540054004' shows up unfortunately often in v3 files).

        Returns ``{"snapped": N, "components": [...]}`` with the modified
        component summaries. ``dry_run=True`` reports what would change.
        """
        from .graph import control_points_of

        p = _get(project_id)

        # Pick target indices.
        if name is None:
            indices = list(range(len(p.components)))
        else:
            i, _c = _find_component(p, name)
            indices = [i]

        def _snap(v: float) -> float:
            return round(v / grid) * grid

        plan: list[tuple[int, int, float, float, float, float]] = []
        for idx in indices:
            c = p.components[idx]
            for cp in control_points_of(c, idx):
                nx, ny = _snap(cp.x), _snap(cp.y)
                if abs(nx - cp.x) > 1e-9 or abs(ny - cp.y) > 1e-9:
                    plan.append((idx, cp.point_index, cp.x, cp.y, nx, ny))

        if dry_run:
            return {
                "dry_run": True,
                "snaps": len(plan),
                "preview": [
                    {
                        "name": getattr(p.components[idx], "name", None),
                        "pin": pi,
                        "from": [ox, oy],
                        "to": [nx, ny],
                    }
                    for (idx, pi, ox, oy, nx, ny) in plan[:20]
                ],
                "truncated": len(plan) > 20,
            }

        if not plan:
            return {"snapped": 0, "components": []}

        _record_history(project_id, f"snap_to_grid ({grid} in)")
        touched_indices: set[int] = set()
        for (idx, pi, _ox, _oy, nx, ny) in plan:
            from . import moves as _m
            cur = control_points_of(p.components[idx], idx)
            cp = next((x for x in cur if x.point_index == pi), None)
            if cp is None:
                continue
            dx, dy = nx - cp.x, ny - cp.y
            if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                _m.move_node(p, idx, pi, dx, dy)
                touched_indices.add(idx)
        return {
            "snapped": len(plan),
            "components": [
                _component_summary(p.components[i], i)
                for i in sorted(touched_indices)
            ],
        }

    @server.tool()
    def align(
        names: list[str],
        axis: str = "x",
        mode: str = "first",
        project_id: str = "default",
        dry_run: bool = False,
    ) -> dict:
        """Align components on an axis (LLM-friendly cleanup).

        ``axis`` is ``'x'`` (line them up vertically — share x coord) or
        ``'y'`` (line them up horizontally — share y coord).
        ``mode`` is ``'first'`` (use the first named component's coord),
        ``'mean'`` (centroid), ``'min'``, or ``'max'``.

        Operates on each component's *anchor* point (x/y for single-anchor
        parts; the centroid of x1/y1/x2/y2 for two-point parts; the
        centroid of points[] for polyline parts). Translates the whole
        component by the required delta.
        """
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        if mode not in ("first", "mean", "min", "max"):
            raise ValueError("mode must be one of: first, mean, min, max")
        if len(names) < 2:
            raise ValueError("align needs at least 2 component names")
        p = _get(project_id)

        from .graph import control_points_of
        targets: list[tuple[int, float, float]] = []
        for nm in names:
            i, c = _find_component(p, nm)
            cps = list(control_points_of(c, i))
            if not cps:
                continue
            cx = sum(cp.x for cp in cps) / len(cps)
            cy = sum(cp.y for cp in cps) / len(cps)
            targets.append((i, cx, cy))

        if not targets:
            return {"aligned": 0, "components": []}

        coords = [t[1] if axis == "x" else t[2] for t in targets]
        if mode == "first":
            anchor = coords[0]
        elif mode == "mean":
            anchor = sum(coords) / len(coords)
        elif mode == "min":
            anchor = min(coords)
        else:  # max
            anchor = max(coords)

        from . import moves as _m
        plan = []
        for (i, cx, cy) in targets:
            cur = cx if axis == "x" else cy
            d = anchor - cur
            if abs(d) > 1e-9:
                plan.append((i, d))

        if dry_run:
            return {
                "dry_run": True,
                "axis": axis,
                "mode": mode,
                "anchor": anchor,
                "moves": [
                    {
                        "name": getattr(p.components[i], "name", None),
                        "delta": d,
                    }
                    for (i, d) in plan
                ],
            }

        if not plan:
            return {"aligned": 0, "components": []}

        _record_history(project_id, f"align {axis} ({mode})")
        for (i, d) in plan:
            dx, dy = (d, 0.0) if axis == "x" else (0.0, d)
            _m.move_component(p, i, dx, dy)
        return {
            "aligned": len(plan),
            "components": [
                _component_summary(p.components[i], i) for (i, _d) in plan
            ],
        }

    @server.tool()
    def stats(project_id: str = "default") -> dict:
        """Project-wide summary: counts by type + the bounding box.

        Cheap "what's in here" answer for an LLM that's just opened a
        layout it didn't build. Returns counts by component type and the
        min/max coords across every control point (the actual layout
        extent, distinct from the canvas size).
        """
        from collections import Counter
        from .graph import control_points_of

        p = _get(project_id)
        counts: Counter[str] = Counter(type(c).__name__ for c in p.components)

        xs: list[float] = []
        ys: list[float] = []
        for i, c in enumerate(p.components):
            for cp in control_points_of(c, i):
                xs.append(cp.x)
                ys.append(cp.y)

        if xs and ys:
            bbox = {
                "min_x": min(xs), "min_y": min(ys),
                "max_x": max(xs), "max_y": max(ys),
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
            }
        else:
            bbox = None

        return {
            "title": p.title,
            "author": p.author,
            "components": len(p.components),
            "canvas_cm": [p.width_cm, p.height_cm],
            "canvas_in": [p.width_cm / 2.54, p.height_cm / 2.54],
            "by_type": [
                {"type": t, "count": n}
                for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "bbox_in": bbox,
        }

    @server.tool()
    def validate(project_id: str = "default") -> dict:
        """Check the project for problems. Returns a structured report.

        Each issue has a ``severity``: ``"error"`` for things that will
        actually break (duplicate names corrupt the viewer's AST edits;
        missing names break the catalog), or ``"info"`` for things that
        are technically off but are common in real DIYLC layouts (e.g.
        off-canvas hardware, since ~half the upstream corpus places
        jacks, pots, and labels outside the strict canvas bounds for
        layout clarity).

        ``ok`` is True when there are no ``error``-severity issues.
        Errors block save-time confidence; infos are informational and
        a clean project may still have them.

        Returns ``{ok, components, issues, errors, infos}`` where
        ``errors`` and ``infos`` are convenience filters over ``issues``.
        """
        from collections import Counter
        from .graph import control_points_of

        p = _get(project_id)
        issues: list[dict] = []

        # 1. Duplicate names — error. These break the viewer's AST edits
        # (move_component finds the wrong instance by name).
        names = [getattr(c, "name", None) for c in p.components]
        counts = Counter(n for n in names if n)
        for nm, n in counts.items():
            if n > 1:
                issues.append({
                    "severity": "error",
                    "kind": "duplicate_name",
                    "name": nm,
                    "count": n,
                    "message": f"{n} components share the name {nm!r}",
                })

        # 2. Empty / missing names — error. Catalog and search depend on names.
        for i, n in enumerate(names):
            if not n:
                issues.append({
                    "severity": "error",
                    "kind": "missing_name",
                    "index": i,
                    "type": type(p.components[i]).__name__,
                    "message": "component has no name",
                })

        # 3. Off-canvas geometry — info. About half the upstream DIYLC
        # corpus has off-canvas components (jacks, pots, labels deliberately
        # offset from the PCB area for layout clarity). Flagging this as
        # an error would make validate noisy and untrustworthy.
        w_in = p.width_cm / 2.54
        h_in = p.height_cm / 2.54
        for i, c in enumerate(p.components):
            for cp in control_points_of(c, i):
                if cp.x < 0 or cp.x > w_in or cp.y < 0 or cp.y > h_in:
                    issues.append({
                        "severity": "info",
                        "kind": "off_canvas",
                        "name": getattr(c, "name", None),
                        "type": type(c).__name__,
                        "point": [cp.x, cp.y],
                        "canvas": [w_in, h_in],
                        "message": (
                            f"control point ({cp.x:.2f}, {cp.y:.2f}) is outside "
                            f"the {w_in:.1f}×{h_in:.1f} in canvas — common for "
                            "off-board hardware (jacks, pots, labels)"
                        ),
                    })
                    break  # one issue per component is enough

        errors = [i for i in issues if i["severity"] == "error"]
        infos = [i for i in issues if i["severity"] == "info"]
        return {
            "ok": not errors,
            "components": len(p.components),
            "issues": issues,
            "errors": errors,
            "infos": infos,
        }

    # =====================================================================
    # Undo / Redo (mirrors the viewer's session history)
    # =====================================================================

    @server.tool()
    def undo(project_id: str = "default") -> dict:
        """Undo the most recent mutating tool call on this project.

        Tracks the same actions the viewer's history does (add, remove,
        move, rotate, duplicate, set_value, connect, ...). Returns a
        dict with ``undone`` (bool) and the resulting component count."""
        p = _get(project_id)
        h = _history_for(project_id)
        ok = h.undo()
        return {
            "undone": ok,
            "components": len(p.components),
            "can_undo": h.can_undo(),
            "can_redo": h.can_redo(),
        }

    @server.tool()
    def redo(project_id: str = "default") -> dict:
        """Redo the most recently undone action. Returns the same shape
        as ``undo``."""
        p = _get(project_id)
        h = _history_for(project_id)
        ok = h.redo()
        return {
            "redone": ok,
            "components": len(p.components),
            "can_undo": h.can_undo(),
            "can_redo": h.can_redo(),
        }

    @server.tool()
    def history(project_id: str = "default") -> dict:
        """Inspect the undo/redo stack depth + the last action's label.

        Cheap status check before deciding whether to undo, equivalent to
        the bar in the viewer's status line.
        """
        h = _history_for(project_id)
        return {
            "depth": h.depth(),
            "redo_depth": h.redo_depth(),
            "last_label": h.last_label(),
            "can_undo": h.can_undo(),
            "can_redo": h.can_redo(),
        }

    # =====================================================================
    # Save / render / read
    # =====================================================================

    @server.tool()
    def save(
        path: str | None = None,
        project_id: str = "default",
        return_content: bool = False,
    ) -> dict:
        """Save the project to a `.diy` file or return the XML inline.

        ``path`` writes to disk and returns the resolved path. Omit
        ``path`` and set ``return_content=True`` to skip disk I/O entirely
        and get the XML as a string — useful for sandboxed chat UIs.
        """
        p = _get(project_id)
        if return_content or path is None:
            return {
                "content": p.to_xml(),
                "components": len(p.components),
            }
        out = p.save(path)
        return {"path": str(Path(out).resolve()), "components": len(p.components)}

    @server.tool()
    def render_svg(
        path: str | None = None,
        project_id: str = "default",
        dpi: int = 96,
        return_content: bool = False,
    ) -> dict:
        """Render the project to SVG.

        Default behavior writes the SVG to ``path`` and returns the
        resolved path. With ``return_content=True`` (or no ``path``) the
        SVG markup is returned inline as ``content`` — chat-friendly,
        no filesystem access needed.
        """
        from .svg import render_svg as _render_svg, RenderOptions

        p = _get(project_id)
        svg_text = _render_svg(p, RenderOptions(px_per_inch=dpi))
        if return_content or path is None:
            return {"content": svg_text}
        out = Path(path)
        out.write_text(svg_text, encoding="utf-8")
        return {"path": str(out.resolve())}

    @server.tool()
    def render_png(
        path: str | None = None,
        project_id: str = "default",
        dpi: int = 96,
        return_content: bool = False,
    ) -> dict:
        """Render the project to a PNG file (or return base64-encoded bytes).

        Requires pycairo (``pip install pydiylc[viewer]``). With
        ``return_content=True`` (or no ``path``) returns the PNG payload
        as base64 in ``content_base64`` so chat clients without
        filesystem access can preview the image.
        """
        from .cairo_render import render_png as _render_png

        p = _get(project_id)
        if return_content or path is None:
            import base64, io, tempfile, os
            # cairo's render_png takes a file path; route through a temp file.
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp_path = tf.name
            try:
                _render_png(p, tmp_path, dpi=dpi)
                data = Path(tmp_path).read_bytes()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return {
                "content_base64": base64.b64encode(data).decode("ascii"),
                "bytes": len(data),
            }
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
        _HISTORIES.pop(project_id, None)
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
            "Discover what's available, then build the layout in one batch:\n\n"
            "1. `list_categories()` to see component categories (passive, "
            "semiconductors, boards, electromechanical, ...). Optional: read "
            "`pydiylc://catalog` for the full schema once.\n\n"
            f"2. `create_project(project_id='pedal', title={name!r}, "
            "width_cm=18, height_cm=10)`.\n\n"
            "3. Use `add_components([...])` with one batch call for the whole "
            "layout — it's much cheaper than many `add_component` calls. "
            "A typical small pedal needs:\n"
            "   - One `VeroBoard` (stripboard) around (1,1)→(2.2,1.7)\n"
            "   - The active component: `TransistorTO92`, `DIL_IC`, or `TransistorTO220`\n"
            "   - Passives: `Resistor`, `RadialFilmCapacitor`, `RadialElectrolytic`\n"
            "   - One `PotentiometerPanel` (taper='LOG' for volume)\n"
            "   - Jacks: `OpenJack1_4` (input/output), `PlasticDCJack` (power)\n"
            "   - A `MiniToggleSwitch` with switch_type='_3PDT' for true bypass\n"
            "   - `SolderPad` at every junction\n\n"
            "4. Wire it up with `connect(from_name, to_name)` — picks the "
            "nearest pin pair automatically. For PCB traces, pass kind='trace'.\n\n"
            "5. `snap_to_grid()` to clean up any off-grid coords, then "
            "`align()` to tidy rows of pads if needed.\n\n"
            "6. `validate()` — catches duplicate names, off-canvas geometry, "
            "and other common bugs. Fix any issues it reports.\n\n"
            "7. `render_svg(return_content=True)` for an inline preview "
            "(or `render_svg('preview.svg')` to write a file). Then "
            "`save('layout.diy')` to emit the DIYLC file.\n\n"
            "Coordinate hygiene: every position should be on the 0.1 in grid. "
            "The catalog (or `describe_component_type`) lists which fields are "
            "required vs. defaulted. Mistakes are recoverable — every mutating "
            "tool records an undo snapshot, and `undo()` reverts the last one.\n\n"
            "**Discriminator trap**: when a component has a `type` field of "
            "its own (jacks: MONO/STEREO; solder pads: ROUND/SQUARE; "
            "humbuckers: PAF/DOG_EAR; etc.) the dict will have two `type` "
            "keys — Python/JSON keep only the last, dropping the class name. "
            "For these, use `_type` for the class name and leave `type` for "
            "the field value: "
            "`{'_type': 'OpenJack1_4', 'name': 'J1', 'type': 'MONO'}`. "
            "The loader raises a clear error if you hit this."
        )

    @server.prompt()
    def modify_existing_layout(diy_path: str = "input.diy") -> str:
        """Walkthrough for reading an existing layout and making edits."""
        return (
            f"Read the existing layout at {diy_path!r} and tweak it.\n\n"
            f"1. `read_diy(path={diy_path!r}, project_id='layout')` to load it. "
            "The reader handles modern, v3 XStream, and v1 `<Layout>` formats "
            "(100% recognition on the upstream DIYLC corpus).\n\n"
            "2. `stats('layout')` for a one-call summary: component count, "
            "counts by type, the actual bounding box of the layout.\n\n"
            "3. `find_components('R3')` (fuzzy match) to locate components by "
            "name fragment — typos OK. `get_pins(name)` shows every "
            "addressable control point of one component.\n\n"
            "4. Apply edits:\n"
            "   - Move: `move_component(name, dx, dy)` is connection-aware "
            "(drags coincident wires); `move_node(name, point_index, dx, dy)` "
            "deliberately detaches a single endpoint.\n"
            "   - Rotate: `rotate_component(name)` cycles `orientation` "
            "if present, otherwise rotates coords about the centroid.\n"
            "   - Value: `set_value(name, '47K')` for the primary value "
            "field; `set_fields(name, {field: value, ...})` for several "
            "attributes atomically.\n"
            "   - Duplicate / remove: `duplicate_component(name)`, "
            "`remove_component(name)`.\n"
            "   - Wire: `connect(from_name, to_name)` picks the nearest pin "
            "pair automatically.\n\n"
            "5. Made a mistake? `undo()` reverts the last action; `history()` "
            "shows the stack depth and last action label.\n\n"
            "6. `validate()` before save to catch issues. `to_json()` "
            "inspects the final state; `save(path)` writes the new `.diy`.\n\n"
            "Error messages include 'did you mean X?' hints for any "
            "component/project/field name lookup — use them to self-correct typos."
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
