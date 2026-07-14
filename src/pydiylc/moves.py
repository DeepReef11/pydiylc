"""Move engine — applies connection-aware moves to a Project.

Step 2 of the keyboard tree editor (see ``docs/keyboard-tree-editor.md``).
Pure and headless. Given a connectivity graph and a requested move, it
computes which control points should shift and by how much, honoring the
mount / wire / rigid attachment rules, then mutates the components.

Two granularities of move:

- **component move** (``move_component`` / ``move_components``): the selection
  translates by Δ, carrying what is genuinely attached to it — the components
  mounted on a moving board, and the wires soldered to a moving pin (far end
  anchored, so leads stretch). Nothing else follows: a wire never anchors
  another wire, so two lines that merely overlap are not joined. Pass
  ``detach=True`` to move the selection alone and break its joints. See
  ``_translate_group``.

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


def _leads_to_follow(
    project: Project, g: ConnectivityGraph, rigid_set: set[int]
) -> list[tuple[int, int]]:
    """Wire endpoints soldered to a moving pin, which travel with it.

    An endpoint follows iff it shares a junction with a *rigid* pin belonging
    to the moving set, and with no rigid pin outside it. Move a pad and the
    lead soldered to it comes along, far end anchored, so the wire stretches.

    Two conditions, two different disasters averted:

    - The anchor must be rigid. A wire never anchors another wire — both ends
      are elastic, so two of them sharing a coordinate are merely touching,
      not joined. Without this, parking a line on a bus and taking it off
      again dragged the whole bus along underneath it.

    - No rigid anchor outside the moving set. Once the user has dragged a
      moving component on top of a stationary one, the junction holds both;
      pulling the lead along would silently unplug it from the part they never
      touched. Leave it stretched instead — a stretched wire is at least
      visible.

    Called *before* the move, while the junctions still describe the old
    layout.
    """
    components = project.components
    follow: list[tuple[int, int]] = []
    for i, wire in enumerate(components):
        if i in rigid_set or not is_wire_like(wire):
            continue
        for cp in control_points_of(wire, i):
            j = g.junction_at(cp.x, cp.y)
            if j is None:
                continue
            anchors = {
                m.component_index
                for m in j.members
                if m.component_index != i
                and not is_wire_like(components[m.component_index])
            }
            if anchors and anchors <= rigid_set:
                follow.append((i, cp.point_index))
    return follow


def _translate_group(
    project: Project, g: ConnectivityGraph, rigid_set: set[int],
    dx: float, dy: float, *, detach: bool = False,
) -> MoveResult:
    """Translate ``rigid_set`` by (dx, dy), carrying its soldered leads.

    Three rules, and nothing else propagates:

    - Containment: a board carries the components mounted on it.
    - Leads follow: a wire endpoint soldered to a moving pin travels with it,
      far end anchored, so the wire stretches (see ``_leads_to_follow``).
    - Stretch, don't unplug: an endpoint of a *moving* wire that is anchored
      on a pin outside the set stays put, so the wire stretches rather than
      silently unplugging a component the user never selected. Both ends can
      be pinned this way, in which case the wire doesn't move at all.

    ``detach=True`` drops the lead-following rule: the selection moves alone
    and every joint it had is broken. That's the deliberate way to pull a part
    off its wires — and the escape hatch for the one case geometry can't
    resolve, a part parked exactly on a rail's endpoint.
    """
    components = project.components
    result = MoveResult()

    # Resolve the topology up front — once the components move, the junctions
    # they used to sit on are gone.
    follow = [] if detach else _leads_to_follow(project, g, rigid_set)
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

    # Drag each soldered lead to its pin's new position. The far end stays,
    # so the wire stretches.
    for (wi, pi) in follow:
        wire = components[wi]
        wp = next(
            (p for p in control_points_of(wire, wi) if p.point_index == pi),
            None,
        )
        if wp is None:
            continue
        new_x, new_y = _clean(wp.x + dx), _clean(wp.y + dy)
        _set_point(wire, pi, new_x, new_y)
        result.shifts.append(PointShift(wi, pi, (wp.x, wp.y), (new_x, new_y)))

    return result


def move_component(
    project: Project,
    component_index: int,
    dx: float,
    dy: float,
    *,
    graph: ConnectivityGraph | None = None,
    detach: bool = False,
) -> MoveResult:
    """Move one component by (dx, dy), carrying its board's parts and leads.

    A wire soldered to one of this component's pins follows it, far end
    anchored, so the lead stretches. ``detach=True`` leaves every wire behind.
    """
    g = graph or build_graph(project)
    rigid_set = _rigid_set(project, g, [component_index])
    return _translate_group(project, g, rigid_set, dx, dy, detach=detach)


def move_components(
    project: Project,
    component_indices: list[int],
    dx: float,
    dy: float,
    *,
    detach: bool = False,
) -> MoveResult:
    """Rigidly translate a selection by (dx, dy), carrying its soldered leads.

    - Components on a selected board move with it, but only once (no
      double-move from also appearing in the selection list).
    - A wire soldered to a selected pin follows it; its far end stays, so the
      lead stretches. Nothing else in the layout moves.
    - Wires inside the selection translate as a whole — both endpoints shift —
      unless an endpoint is anchored on an *unselected* pin, which holds, so
      the wire stretches instead of unplugging a part the user never selected.

    ``detach=True`` drops the lead-following: the selection moves alone.
    """
    g = build_graph(project)
    rigid_set = _rigid_set(project, g, component_indices)
    return _translate_group(project, g, rigid_set, dx, dy, detach=detach)


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
    detach: bool = False,
) -> RotateResult:
    """Rotate a component 90°, dragging its soldered leads to the new pins.

    Same attachment rule as the move engine: a wire endpoint soldered to one of
    this component's pins tracks that pin to its new position (far end stays).
    A wire never anchors another wire, so spinning a line that overlaps a bus
    leaves the bus alone. ``detach=True`` leaves every wire behind.

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
            components, component_index, pre_pins, detach
        )
        return RotateResult(component_index, "enum", "orientation", orientation, new)

    if orientation in _ORIENT_HV:
        new = _ORIENT_HV[(_ORIENT_HV.index(orientation) + 1) % 2]
        comp.orientation = new
        _follow_wires_after_geometry_change(
            components, component_index, pre_pins, detach
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
        components, component_index, pre_pins, detach
    )
    return RotateResult(component_index, "coords")


def _follow_wires_after_geometry_change(
    components: list,
    component_index: int,
    pre_pins: list,
    detach: bool = False,
) -> None:
    """Drag soldered leads to track a component's per-pin movement.

    Used by rotate_component (and any future geometry-changing operation).
    Matches by pre-change position, so two wires sharing a junction at the same
    old pin both follow that pin to its new location.

    A wire's own pins are elastic, so rotating one drags nothing at all —
    otherwise spinning a line that overlapped a bus would drag the bus along.
    ``detach`` skips the whole thing and leaves every wire where it is.
    """
    if detach or is_wire_like(components[component_index]):
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

    for i, wire in enumerate(components):
        if i == component_index:
            continue
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
