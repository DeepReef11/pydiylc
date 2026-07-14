"""Move engine — applies connection-aware moves to a Project.

Step 2 of the keyboard tree editor (see ``docs/keyboard-tree-editor.md``).
Pure and headless. Given a connectivity graph and a requested move, it
computes which control points should shift and by how much, honoring the
mount / wire / rigid attachment rules, then mutates the components.

Two granularities of move:

- **component move** (``move_component`` / ``move_components``): the selection
  translates by Δ. Attachment is never inferred from geometry — something that
  merely touches the selection is not dragged along; select it too if you want
  it to move. The only propagation is containment (a board carries the
  components mounted on it) and the stretch rule that keeps a selected wire
  plugged into the *unselected* pin it sits on (see ``_translate_group``).

- **node move** (``move_node``): a single control point shifts by Δ. Used for
  the Tab-into-a-node + nudge workflow. Coincident points on *other*
  components are left behind (this is how you detach a lead).

Both return a ``MoveResult`` describing what changed, so the caller (the
viewer) can preview, then commit through the AST-edit path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .components import Component
from .core import Project
from .graph import (
    ConnectivityGraph,
    build_graph,
    components_on_board,
    control_points_of,
    is_wire_like,
)


@dataclass
class PointShift:
    """A single control point that moved."""

    component_index: int
    point_index: int
    old: tuple[float, float]
    new: tuple[float, float]


@dataclass
class MoveResult:
    """What a move changed. Components are already mutated when returned."""

    shifts: list[PointShift] = field(default_factory=list)

    def components_moved(self) -> list[int]:
        seen: list[int] = []
        for s in self.shifts:
            if s.component_index not in seen:
                seen.append(s.component_index)
        return seen


# ---------------------------------------------------------------------------
# Low-level point mutation
# ---------------------------------------------------------------------------


def _set_point(component: Component, point_index: int, x: float, y: float) -> None:
    """Write a single control point back onto a component, by its model."""
    if hasattr(component, "x1") and hasattr(component, "x2"):
        if point_index == 0:
            component.x1, component.y1 = x, y
        else:
            component.x2, component.y2 = x, y
        return
    if hasattr(component, "points"):
        pts = list(component.points)
        pts[point_index] = (x, y)
        component.points = pts
        return
    if hasattr(component, "_control_points"):
        # Multi-node bodies are positioned by their anchor (x, y); we don't
        # move derived pins individually. Shift the anchor instead.
        if hasattr(component, "x") and hasattr(component, "y"):
            # Re-derive: the move engine should call _shift_anchor for these,
            # but if a single pin is targeted we translate the whole body so
            # that pin lands at (x, y).
            pts = component._control_points()
            if 0 <= point_index < len(pts):
                ox, oy = pts[point_index]
                component.x += x - ox
                component.y += y - oy
        return
    if hasattr(component, "x") and hasattr(component, "y"):
        component.x, component.y = x, y
        return
    raise TypeError(f"can't set point on {type(component).__name__}")


def _clean(v: float) -> float:
    return round(float(v), 4)


def _translate_in_place(component: Component, dx: float, dy: float) -> None:
    if hasattr(component, "x1") and hasattr(component, "x2"):
        component.x1 = _clean(component.x1 + dx)
        component.y1 = _clean(component.y1 + dy)
        component.x2 = _clean(component.x2 + dx)
        component.y2 = _clean(component.y2 + dy)
        return
    if hasattr(component, "points"):
        component.points = [
            (_clean(px + dx), _clean(py + dy)) for px, py in component.points
        ]
        return
    if hasattr(component, "x") and hasattr(component, "y"):
        component.x = _clean(component.x + dx)
        component.y = _clean(component.y + dy)
        return


# ---------------------------------------------------------------------------
# Public moves
# ---------------------------------------------------------------------------


def _rigid_set(
    project: Project, g: ConnectivityGraph, indices: Iterable[int]
) -> set[int]:
    """The selection, expanded to include everything mounted on a board in it."""
    from .graph import _BOARD_TYPES  # local import to avoid cycle at top

    rigid: set[int] = set(indices)
    for ci in list(rigid):
        if isinstance(project.components[ci], _BOARD_TYPES):
            rigid.update(components_on_board(g, ci))
    return rigid


def _pinned_outside(
    project: Project, g: ConnectivityGraph, wire_index: int,
    cp, rigid_set: set[int],
) -> bool:
    """True if this wire endpoint is anchored on a pin *outside* the move.

    "Anchored" means the endpoint shares a junction with a rigid (non-wire)
    pin — a component pin, a pad, a board. A wire never anchors another wire:
    both ends are elastic, so two of them sharing a coordinate are merely
    touching. That is what let a line parked on a bus drag the bus away.
    """
    j = g.junction_at(cp.x, cp.y)
    if j is None:
        return False
    return any(
        m.component_index != wire_index
        and m.component_index not in rigid_set
        and not is_wire_like(project.components[m.component_index])
        for m in j.members
    )


def _translate_group(
    project: Project, g: ConnectivityGraph, rigid_set: set[int],
    dx: float, dy: float,
) -> MoveResult:
    """Translate ``rigid_set`` by (dx, dy). Nothing outside the set moves.

    Attachment is never inferred from geometry: a component that merely
    touches the moving set stays exactly where it is. To move something along
    with the selection, select it too — that is the whole attachment
    mechanism, and it's the only one the user can see.

    The single exception keeps *untouched* parts wired up: an endpoint of a
    selected wire that is anchored on a pin outside the set stays put, so the
    wire stretches rather than silently unplugging a component the user never
    selected. Both of a wire's ends can be pinned this way, in which case it
    doesn't move at all.
    """
    components = project.components
    result = MoveResult()

    # Resolve the topology up front — once the components move, the junctions
    # they used to sit on are gone.
    pinned: dict[int, set[int]] = {}
    for ci in rigid_set:
        comp = components[ci]
        if not is_wire_like(comp):
            continue
        pinned[ci] = {
            cp.point_index
            for cp in control_points_of(comp, ci)
            if _pinned_outside(project, g, ci, cp, rigid_set)
        }

    for ci in sorted(rigid_set):
        comp = components[ci]
        before = control_points_of(comp, ci)
        held = pinned.get(ci)
        if not held:
            _translate_in_place(comp, dx, dy)
        else:
            # Shift only the free ends; the pinned ones hold their anchor.
            for cp in before:
                if cp.point_index in held:
                    continue
                _set_point(comp, cp.point_index,
                           _clean(cp.x + dx), _clean(cp.y + dy))
        after = control_points_of(comp, ci)
        for b, a in zip(before, after):
            if (b.x, b.y) == (a.x, a.y):
                continue
            result.shifts.append(
                PointShift(ci, b.point_index, (b.x, b.y), (a.x, a.y))
            )

    return result


def move_component(
    project: Project,
    component_index: int,
    dx: float,
    dy: float,
    *,
    graph: ConnectivityGraph | None = None,
) -> MoveResult:
    """Move one component by (dx, dy). Only it (and its board's parts) move.

    Nothing attaches itself to the move. A wire whose endpoint sits on this
    component's pin does *not* follow — select it too if you want it along.
    """
    g = graph or build_graph(project)
    rigid_set = _rigid_set(project, g, [component_index])
    return _translate_group(project, g, rigid_set, dx, dy)


def move_components(
    project: Project,
    component_indices: list[int],
    dx: float,
    dy: float,
) -> MoveResult:
    """Rigidly translate a selection by (dx, dy).

    The selection *is* the attachment: exactly what's listed moves, plus the
    components mounted on any board in it (they sit on it, so they ride along).
    A component that merely touches the selection never follows.

    - Wires inside the selection translate as a whole — both endpoints shift.
    - A selected wire endpoint anchored on an *unselected* pin stays put, so
      the wire stretches instead of unplugging a component the user never
      selected.
    - Components on a selected board move with it, but only once (no
      double-move from also appearing in the selection list).
    """
    g = build_graph(project)
    rigid_set = _rigid_set(project, g, component_indices)
    return _translate_group(project, g, rigid_set, dx, dy)


def move_node(
    project: Project,
    component_index: int,
    point_index: int,
    dx: float,
    dy: float,
) -> MoveResult:
    """Move a single control point by (dx, dy). Detaches from any junction.

    This is the node-level nudge (Tab into a node, then arrow). Coincident
    points on other components are NOT pulled along — that's how you separate
    a lead from a junction.
    """
    comp = project.components[component_index]
    pts = control_points_of(comp, component_index)
    cp = next((p for p in pts if p.point_index == point_index), None)
    if cp is None:
        raise IndexError(
            f"component {component_index} has no point {point_index}"
        )
    new = (_clean(cp.x + dx), _clean(cp.y + dy))
    _set_point(comp, point_index, new[0], new[1])
    return MoveResult([PointShift(component_index, point_index, (cp.x, cp.y), new)])


def move_node_to(
    project: Project,
    component_index: int,
    point_index: int,
    x: float,
    y: float,
) -> MoveResult:
    """Move a control point to an absolute (x, y) — used by jump-to-target."""
    comp = project.components[component_index]
    pts = control_points_of(comp, component_index)
    cp = next((p for p in pts if p.point_index == point_index), None)
    if cp is None:
        raise IndexError(
            f"component {component_index} has no point {point_index}"
        )
    new = (_clean(x), _clean(y))
    _set_point(comp, point_index, new[0], new[1])
    return MoveResult([PointShift(component_index, point_index, (cp.x, cp.y), new)])


# Orientation enum cycles. Cycling forward = 90° clockwise (or H<->V).
_ORIENT_4 = ("DEFAULT", "_90", "_180", "_270")
_ORIENT_HV = ("HORIZONTAL", "VERTICAL")


@dataclass
class RotateResult:
    """What a rotation changed. The component is already mutated."""

    component_index: int
    kind: str  # "enum" or "coords"
    field: str | None = None  # the orientation field, when kind == "enum"
    old_value: str | None = None
    new_value: str | None = None


def rotate_component(
    project: Project, component_index: int, *, clockwise: bool = True,
    follow: Iterable[int] = (),
) -> RotateResult:
    """Rotate a component 90°, dragging the endpoints of selected wires.

    ``follow`` is the set of component indices the caller has selected. Only a
    wire in that set may have an endpoint dragged to a new pin position;
    everything else keeps its coordinates. Same rule as the move engine — the
    selection is the attachment, never the geometry — so spinning a part does
    not silently rewire whatever happened to be touching its pins.

    Strategy depends on the component:

    - Has a 4-way ``orientation`` (DEFAULT/_90/_180/_270): cycle the enum, so
      derived pins re-orient cleanly. This is the right primitive for pots,
      transistors, ICs, jacks, labels, etc.
    - Has a 2-way ``orientation`` (HORIZONTAL/VERTICAL): toggle it.
    - Otherwise (two-pin, points-list): rotate the raw coordinates 90° about
      the component's centroid.

    After the rotation, any wire endpoint that was sitting on one of
    this component's pins (pre-rotate) is moved to that pin's new
    position. The wire's other endpoint stays.
    """
    comp = project.components[component_index]
    orientation = getattr(comp, "orientation", None)

    # Snapshot the pre-rotate pin positions BEFORE we change orientation
    # or coords, so we can match wire endpoints by their old locations.
    pre_pins = list(control_points_of(comp, component_index))
    components = project.components

    if orientation in _ORIENT_4:
        idx = _ORIENT_4.index(orientation)
        new = _ORIENT_4[(idx + (1 if clockwise else -1)) % 4]
        comp.orientation = new
        _follow_wires_after_geometry_change(
            components, component_index, pre_pins, follow
        )
        return RotateResult(component_index, "enum", "orientation", orientation, new)

    if orientation in _ORIENT_HV:
        new = _ORIENT_HV[(_ORIENT_HV.index(orientation) + 1) % 2]
        comp.orientation = new
        _follow_wires_after_geometry_change(
            components, component_index, pre_pins, follow
        )
        return RotateResult(component_index, "enum", "orientation", orientation, new)

    # Coordinate rotation about the centroid of the component's points.
    if not pre_pins:
        return RotateResult(component_index, "coords")
    cx = sum(p.x for p in pre_pins) / len(pre_pins)
    cy = sum(p.y for p in pre_pins) / len(pre_pins)
    for cp in pre_pins:
        # 90° CW about (cx, cy): (x, y) -> (cx + (y - cy), cy - (x - cx))
        # 90° CCW: (x, y) -> (cx - (y - cy), cy + (x - cx))
        if clockwise:
            nx = cx + (cp.y - cy)
            ny = cy - (cp.x - cx)
        else:
            nx = cx - (cp.y - cy)
            ny = cy + (cp.x - cx)
        _set_point(comp, cp.point_index, _clean(nx), _clean(ny))
    _follow_wires_after_geometry_change(
        components, component_index, pre_pins, follow
    )
    return RotateResult(component_index, "coords")


def _follow_wires_after_geometry_change(
    components: list,
    component_index: int,
    pre_pins: list,
    follow: Iterable[int] = (),
) -> None:
    """Move selected wires' endpoints to track a component's per-pin movement.

    Used by rotate_component (and any future geometry-changing operation).
    Matches by pre-change position, so two selected wires sharing a junction
    at the same old pin both follow that pin to its new location.

    Only wires in ``follow`` (the caller's selection) move. Everything else
    keeps its coordinates, however exactly it happens to touch a pin — the
    selection is the attachment, never the geometry.

    A wire's own pins are elastic, so rotating one drags nothing at all;
    otherwise spinning a line that overlapped a bus would drag the bus along.
    """
    if is_wire_like(components[component_index]):
        return

    post_pins = control_points_of(components[component_index], component_index)
    if len(post_pins) != len(pre_pins):
        return  # shape change; can't pair-up pins safely
    # Map pre-position → post-position (one entry per pin).
    pin_moves: dict[tuple[float, float], tuple[float, float]] = {}
    tol = 1e-6
    for pre, post in zip(pre_pins, post_pins):
        # If a pin didn't move, no follow needed.
        if abs(pre.x - post.x) < tol and abs(pre.y - post.y) < tol:
            continue
        pin_moves[(pre.x, pre.y)] = (post.x, post.y)
    if not pin_moves:
        return

    def _close(a: float, b: float) -> bool:
        return abs(a - b) < tol

    follow_set = set(follow)
    for i, wire in enumerate(components):
        if i == component_index or i not in follow_set:
            continue  # not selected → not attached
        if not is_wire_like(wire):
            continue
        pts = list(getattr(wire, "points", []))
        if not pts:
            continue
        changed = False
        new_pts: list[tuple[float, float]] = []
        for (px, py) in pts:
            moved = False
            for (old_x, old_y), (new_x, new_y) in pin_moves.items():
                if _close(px, old_x) and _close(py, old_y):
                    new_pts.append((_clean(new_x), _clean(new_y)))
                    moved = True
                    changed = True
                    break
            if not moved:
                new_pts.append((px, py))
        if changed:
            wire.points = new_pts
