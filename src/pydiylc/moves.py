"""Move engine — applies connection-aware moves to a Project.

Step 2 of the keyboard tree editor (see ``docs/keyboard-tree-editor.md``).
Pure and headless. Given a connectivity graph and a requested move, it
computes which control points should shift and by how much, honoring the
mount / wire / rigid attachment rules, then mutates the components.

Two granularities of move:

- **component move** (``move_component``): the whole component translates by
  Δ. If it's a board, every mounted component goes with it. Wire endpoints
  coincident with any moved point follow (stay connected); the wire's other
  end stays, so leads stretch.

- **node move** (``move_node``): a single control point shifts by Δ. Used for
  the Tab-into-a-node + nudge workflow. Coincident points on *other*
  components are left behind (this is how you detach a lead).

Both return a ``MoveResult`` describing what changed, so the caller (the
viewer) can preview, then commit through the AST-edit path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .components import Component
from .core import Project
from .graph import (
    ConnectivityGraph,
    EdgeType,
    build_graph,
    components_on_board,
    control_points_of,
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


def move_component(
    project: Project,
    component_index: int,
    dx: float,
    dy: float,
    *,
    graph: ConnectivityGraph | None = None,
) -> MoveResult:
    """Move a whole component by (dx, dy), propagating per attachment rules.

    - Board → all mounted components move with it.
    - Any wire endpoint coincident with a moved point follows (stays
      connected); the wire's far endpoint stays (leads stretch).
    """
    g = graph or build_graph(project)
    components = project.components
    target = components[component_index]

    result = MoveResult()

    # Determine the set of components to translate rigidly.
    rigid_set = {component_index}
    from .graph import _BOARD_TYPES  # local import to avoid cycle at top

    if isinstance(target, _BOARD_TYPES):
        for ci in components_on_board(g, component_index):
            rigid_set.add(ci)

    # Collect the post-move positions of every point on the rigid set so we
    # can find wire endpoints that should follow.
    moved_points: dict[tuple[int, int], tuple[float, float]] = {}
    pre_positions: dict[tuple[int, int], tuple[float, float]] = {}
    for ci in rigid_set:
        for cp in control_points_of(components[ci], ci):
            pre_positions[(ci, cp.point_index)] = (cp.x, cp.y)

    # Translate the rigid set.
    for ci in sorted(rigid_set):
        comp = components[ci]
        before = control_points_of(comp, ci)
        _translate_in_place(comp, dx, dy)
        after = control_points_of(comp, ci)
        for b, a in zip(before, after):
            result.shifts.append(
                PointShift(ci, b.point_index, (b.x, b.y), (a.x, a.y))
            )
            moved_points[(ci, b.point_index)] = (a.x, a.y)

    # Pull along wire endpoints that were coincident with any pre-move point
    # of the rigid set, but only if the wire itself is not in the rigid set.
    tol = g.tolerance
    for e in g.edges:
        if e.edge_type is not EdgeType.WIRE:
            continue
        if e.component_index in rigid_set:
            continue
        wire = components[e.component_index]
        wpts = control_points_of(wire, e.component_index)
        wp = next((p for p in wpts if p.point_index == e.point_index), None)
        if wp is None:
            continue
        # Was this wire endpoint sitting on a (pre-move) rigid point?
        for (ci, pi), (ox, oy) in pre_positions.items():
            if abs(wp.x - ox) <= tol and abs(wp.y - oy) <= tol:
                nx, ny = moved_points[(ci, pi)]
                _set_point(wire, e.point_index, _clean(nx), _clean(ny))
                result.shifts.append(
                    PointShift(e.component_index, e.point_index,
                               (wp.x, wp.y), (_clean(nx), _clean(ny)))
                )
                break

    return result


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
    project: Project, component_index: int, *, clockwise: bool = True
) -> RotateResult:
    """Rotate a component 90°.

    Strategy depends on the component:

    - Has a 4-way ``orientation`` (DEFAULT/_90/_180/_270): cycle the enum, so
      derived pins re-orient cleanly. This is the right primitive for pots,
      transistors, ICs, jacks, labels, etc.
    - Has a 2-way ``orientation`` (HORIZONTAL/VERTICAL): toggle it.
    - Otherwise (two-pin, points-list): rotate the raw coordinates 90° about
      the component's centroid.
    """
    comp = project.components[component_index]
    orientation = getattr(comp, "orientation", None)

    if orientation in _ORIENT_4:
        idx = _ORIENT_4.index(orientation)
        new = _ORIENT_4[(idx + (1 if clockwise else -1)) % 4]
        comp.orientation = new
        return RotateResult(component_index, "enum", "orientation", orientation, new)

    if orientation in _ORIENT_HV:
        new = _ORIENT_HV[(_ORIENT_HV.index(orientation) + 1) % 2]
        comp.orientation = new
        return RotateResult(component_index, "enum", "orientation", orientation, new)

    # Coordinate rotation about the centroid of the component's points.
    pts = control_points_of(comp, component_index)
    if not pts:
        return RotateResult(component_index, "coords")
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    for cp in pts:
        # 90° CW about (cx, cy): (x, y) -> (cx + (y - cy), cy - (x - cx))
        # 90° CCW: (x, y) -> (cx - (y - cy), cy + (x - cx))
        if clockwise:
            nx = cx + (cp.y - cy)
            ny = cy - (cp.x - cx)
        else:
            nx = cx - (cp.y - cy)
            ny = cy + (cp.x - cx)
        _set_point(comp, cp.point_index, _clean(nx), _clean(ny))
    return RotateResult(component_index, "coords")
