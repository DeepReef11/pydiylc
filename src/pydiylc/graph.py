"""Connectivity graph for a Project.

Builds the data model the keyboard tree editor needs (see
``docs/keyboard-tree-editor.md``): every control point of every component,
the *junctions* where points coincide, and the *typed edges* describing how
each component attaches (mounted on a board, wired by a lead, or a rigid
multi-pin body).

This module is pure and headless — no GTK. It's the foundation for the move
engine and the eventual tree-editor UI.

Coordinates are compared after rounding to a tolerance (default 0.001 in) so
float noise doesn't split a real junction into two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .components import (
    Component,
    BlankBoard,
    PerfBoard,
    VeroBoard,
    CopperTrace,
    CurvedTrace,
    HookupWire,
    Jumper,
    Line,
)
from .core import Project


# Components that are "boards" — things other components mount onto.
_BOARD_TYPES = (BlankBoard, PerfBoard, VeroBoard)

# Components whose endpoints are elastic leads/wires (moving one end stretches
# them rather than dragging the far end).
_WIRE_TYPES = (CopperTrace, CurvedTrace, HookupWire, Jumper, Line)

DEFAULT_TOLERANCE = 0.001


class EdgeType(str, Enum):
    MOUNT = "mount"      # component sits on a board
    WIRE = "wire"        # elastic lead/trace/jumper endpoint
    RIGID = "rigid"      # a component's own control point (pin of a body)


@dataclass(frozen=True)
class ControlPoint:
    """One movable point of one component."""

    component_index: int
    point_index: int
    x: float
    y: float


@dataclass
class Junction:
    """A coordinate that one or more control points share."""

    x: float
    y: float
    members: list[ControlPoint] = field(default_factory=list)

    @property
    def shared(self) -> bool:
        """True if more than one component touches this junction."""
        return len({cp.component_index for cp in self.members}) > 1


@dataclass
class Edge:
    """A component's attachment at a control point, with an inferred type."""

    component_index: int
    point_index: int
    edge_type: EdgeType
    # For MOUNT edges, the board the point sits on.
    board_index: int | None = None


@dataclass
class ConnectivityGraph:
    project: Project
    junctions: list[Junction]
    edges: list[Edge]
    tolerance: float = DEFAULT_TOLERANCE

    def junction_at(self, x: float, y: float) -> Junction | None:
        for j in self.junctions:
            if abs(j.x - x) <= self.tolerance and abs(j.y - y) <= self.tolerance:
                return j
        return None

    def components_touching(self, junction: Junction) -> list[int]:
        """Distinct component indices that share this junction."""
        seen: list[int] = []
        for cp in junction.members:
            if cp.component_index not in seen:
                seen.append(cp.component_index)
        return seen


# ---------------------------------------------------------------------------
# Control-point extraction
# ---------------------------------------------------------------------------


def control_points_of(component: Component, index: int) -> list[ControlPoint]:
    """Return the movable control points of a component.

    - two-pin (x1,y1,x2,y2): two points.
    - points-list: one per point.
    - multi-node (auto _control_points): the derived pins (informational —
      the move engine treats them as a rigid body keyed on the anchor).
    - single-anchor (x,y): one point.
    """
    if hasattr(component, "x1") and hasattr(component, "x2"):
        return [
            ControlPoint(index, 0, float(component.x1), float(component.y1)),
            ControlPoint(index, 1, float(component.x2), float(component.y2)),
        ]
    if hasattr(component, "points"):
        return [
            ControlPoint(index, i, float(px), float(py))
            for i, (px, py) in enumerate(component.points)
        ]
    if hasattr(component, "_control_points"):
        pts = component._control_points()
        return [
            ControlPoint(index, i, float(px), float(py))
            for i, (px, py) in enumerate(pts)
        ]
    if hasattr(component, "x") and hasattr(component, "y"):
        return [ControlPoint(index, 0, float(component.x), float(component.y))]
    return []


def _board_rect(board: Component) -> tuple[float, float, float, float]:
    x1, x2 = sorted((float(board.x1), float(board.x2)))
    y1, y2 = sorted((float(board.y1), float(board.y2)))
    return x1, y1, x2, y2


def _point_in_rect(x: float, y: float, rect: tuple[float, float, float, float],
                   tol: float) -> bool:
    x1, y1, x2, y2 = rect
    return (x1 - tol) <= x <= (x2 + tol) and (y1 - tol) <= y <= (y2 + tol)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph(project: Project, tolerance: float = DEFAULT_TOLERANCE) -> ConnectivityGraph:
    components = project.components

    # 1. Gather every control point.
    all_points: list[ControlPoint] = []
    for i, comp in enumerate(components):
        all_points.extend(control_points_of(comp, i))

    # 2. Cluster coincident points into junctions.
    junctions: list[Junction] = []
    for cp in all_points:
        existing = None
        for j in junctions:
            if abs(j.x - cp.x) <= tolerance and abs(j.y - cp.y) <= tolerance:
                existing = j
                break
        if existing is None:
            junctions.append(Junction(cp.x, cp.y, [cp]))
        else:
            existing.members.append(cp)

    # 3. Classify each component's points into typed edges.
    boards = [(i, c) for i, c in enumerate(components) if isinstance(c, _BOARD_TYPES)]
    board_rects = {i: _board_rect(c) for i, c in boards}

    edges: list[Edge] = []
    for i, comp in enumerate(components):
        if isinstance(comp, _BOARD_TYPES):
            # A board's own corners are rigid (the board body).
            for cp in control_points_of(comp, i):
                edges.append(Edge(i, cp.point_index, EdgeType.RIGID))
            continue
        if isinstance(comp, _WIRE_TYPES):
            for cp in control_points_of(comp, i):
                edges.append(Edge(i, cp.point_index, EdgeType.WIRE))
            continue
        # Everything else: mounted if any control point lies on a board,
        # otherwise rigid (a free-floating body).
        cps = control_points_of(comp, i)
        for cp in cps:
            mounted_on = None
            for bidx, rect in board_rects.items():
                if _point_in_rect(cp.x, cp.y, rect, tolerance):
                    mounted_on = bidx
                    break
            if mounted_on is not None:
                edges.append(Edge(i, cp.point_index, EdgeType.MOUNT, board_index=mounted_on))
            else:
                edges.append(Edge(i, cp.point_index, EdgeType.RIGID))

    return ConnectivityGraph(project, junctions, edges, tolerance)


def components_on_board(graph: ConnectivityGraph, board_index: int) -> list[int]:
    """Return the indices of components mounted on the given board."""
    out: list[int] = []
    for e in graph.edges:
        if e.edge_type is EdgeType.MOUNT and e.board_index == board_index:
            if e.component_index not in out:
                out.append(e.component_index)
    return out
