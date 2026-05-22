"""Jump-to-target move mode (vim-flash style).

With a node focused, the user presses an arrow; this module computes the
legal destinations in that direction — other junctions and perfboard /
stripboard holes — sorted nearest-first and labelled with hint keys. The
viewer overlays the hints; pressing one snaps the node there.

Pure and headless: candidate-finding and hint assignment are testable
without GTK. The overlay rendering and hint-key capture live in viewer.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .components import PerfBoard, VeroBoard
from .core import Measure, Project
from .graph import ConnectivityGraph, build_graph


# Home-row-first hint keys, like easymotion/flash.
_HINT_KEYS = "fjdkslaghrueiwovncmtybp"


@dataclass(frozen=True)
class Target:
    """A candidate jump destination."""

    x: float
    y: float
    hint: str
    kind: str  # "junction" or "hole"
    distance: float


def _measure_in(m: Measure) -> float:
    if m.unit == "in":
        return m.value
    if m.unit == "mm":
        return m.value / 25.4
    if m.unit == "cm":
        return m.value / 2.54
    return m.value


def _board_holes(board) -> list[tuple[float, float]]:
    """Hole positions of a perf/stripboard on its grid."""
    x1, x2 = sorted((float(board.x1), float(board.x2)))
    y1, y2 = sorted((float(board.y1), float(board.y2)))
    step = _measure_in(board.spacing)
    if step <= 0:
        return []
    holes: list[tuple[float, float]] = []
    nx = int(round((x2 - x1) / step))
    ny = int(round((y2 - y1) / step))
    for i in range(nx + 1):
        for j in range(ny + 1):
            holes.append((round(x1 + i * step, 4), round(y1 + j * step, 4)))
    return holes


def _direction_ok(dx: float, dy: float, direction: str, cone_deg: float = 60.0) -> bool:
    """True if (dx, dy) points within ``cone_deg`` of the named direction.

    Directions: 'left', 'right', 'up', 'down'. Y increases downward (canvas).
    """
    if dx == 0 and dy == 0:
        return False
    ang = math.degrees(math.atan2(dy, dx))  # -180..180; 0 = +x (right)
    # Target angle per direction (canvas y-down): right=0, down=90, left=180,
    # up=-90.
    target = {"right": 0.0, "down": 90.0, "left": 180.0, "up": -90.0}[direction]
    diff = abs((ang - target + 180) % 360 - 180)
    return diff <= cone_deg


def find_targets(
    project: Project,
    component_index: int,
    point_index: int,
    direction: str,
    *,
    graph: ConnectivityGraph | None = None,
    include_holes: bool = True,
    max_targets: int | None = None,
) -> list[Target]:
    """Compute jump destinations from a node in a direction.

    Candidates are other junctions and (optionally) perf/stripboard holes,
    within a directional cone, sorted nearest-first, each assigned a hint key.
    The node's own current position is excluded.
    """
    g = graph or build_graph(project)
    from .graph import control_points_of

    comp = project.components[component_index]
    cps = control_points_of(comp, component_index)
    here = next((p for p in cps if p.point_index == point_index), None)
    if here is None:
        return []
    ox, oy = here.x, here.y
    tol = g.tolerance

    raw: list[tuple[float, float, str]] = []

    # Junctions (excluding the one we're sitting on).
    for j in g.junctions:
        if abs(j.x - ox) <= tol and abs(j.y - oy) <= tol:
            continue
        raw.append((j.x, j.y, "junction"))

    # Board holes.
    if include_holes:
        seen = {(round(x, 4), round(y, 4)) for x, y, _ in raw}
        for comp2 in project.components:
            if isinstance(comp2, (PerfBoard, VeroBoard)):
                for hx, hy in _board_holes(comp2):
                    if abs(hx - ox) <= tol and abs(hy - oy) <= tol:
                        continue
                    key = (round(hx, 4), round(hy, 4))
                    if key in seen:
                        continue
                    seen.add(key)
                    raw.append((hx, hy, "hole"))

    # Filter by direction + compute distance.
    scored: list[tuple[float, float, float, str]] = []
    for tx, ty, kind in raw:
        dx, dy = tx - ox, ty - oy
        if not _direction_ok(dx, dy, direction):
            continue
        scored.append((math.hypot(dx, dy), tx, ty, kind))

    scored.sort(key=lambda s: s[0])
    if max_targets is None:
        max_targets = len(_HINT_KEYS)
    scored = scored[:max_targets]

    targets: list[Target] = []
    for idx, (dist, tx, ty, kind) in enumerate(scored):
        if idx >= len(_HINT_KEYS):
            break
        targets.append(Target(tx, ty, _HINT_KEYS[idx], kind, round(dist, 4)))
    return targets


def target_for_hint(targets: list[Target], hint: str) -> Target | None:
    for t in targets:
        if t.hint == hint:
            return t
    return None


# ---------------------------------------------------------------------------
# Arrow-nudge on a perfboard (one hole per press)
# ---------------------------------------------------------------------------


def _board_containing(project: Project, x: float, y: float, tol: float = 0.001):
    """Return the first perf/stripboard whose rect contains (x, y), or None."""
    for comp in project.components:
        if isinstance(comp, (PerfBoard, VeroBoard)):
            x1, x2 = sorted((float(comp.x1), float(comp.x2)))
            y1, y2 = sorted((float(comp.y1), float(comp.y2)))
            if (x1 - tol) <= x <= (x2 + tol) and (y1 - tol) <= y <= (y2 + tol):
                return comp
    return None


def hole_step_for(project: Project, x: float, y: float) -> float | None:
    """The hole spacing (in inches) of the board under (x, y), or None if the
    point isn't on a board. Used to size a one-hole arrow nudge."""
    board = _board_containing(project, x, y)
    if board is None:
        return None
    return _measure_in(board.spacing)


def hole_delta(project: Project, x: float, y: float, direction: str
               ) -> tuple[float, float] | None:
    """Return the (dx, dy) for a one-hole move in ``direction`` from (x, y),
    sized to the board's hole spacing. None if (x, y) isn't on a board."""
    step = hole_step_for(project, x, y)
    if step is None:
        return None
    dx = -step if direction == "left" else step if direction == "right" else 0.0
    dy = -step if direction == "up" else step if direction == "down" else 0.0
    return (round(dx, 4), round(dy, 4))


# ---------------------------------------------------------------------------
# Fuzzy "go to node" search
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapTarget:
    """A labelled destination a node can be sent to via the go-to menu."""

    label: str          # e.g. "R3 end 2", "Q1 pin 1"
    component_index: int
    point_index: int
    x: float
    y: float


def searchable_targets(project: Project, *, exclude_component: int | None = None
                       ) -> list[SnapTarget]:
    """Build the list of named snap destinations (one per addressable node).

    Labels are "<component name> <node>", matching the tree-editor rows so
    the user can type "R3 end2" or "Q1 pin1". The component being moved can be
    excluded so you don't send a node onto its own body.
    """
    from .graph import control_points_of

    out: list[SnapTarget] = []
    for i, comp in enumerate(project.components):
        if i == exclude_component:
            continue
        name = getattr(comp, "name", f"#{i}")
        cps = control_points_of(comp, i)
        if hasattr(comp, "x1") and hasattr(comp, "x2"):
            node_labels = {0: "end 1", 1: "end 2"}
        elif hasattr(comp, "points"):
            node_labels = {cp.point_index: f"point {cp.point_index + 1}" for cp in cps}
        elif hasattr(comp, "_control_points"):
            node_labels = {cp.point_index: f"pin {cp.point_index + 1}" for cp in cps}
        else:
            node_labels = {0: ""}  # single anchor: just the component
        for cp in cps:
            suffix = node_labels.get(cp.point_index, f"pt{cp.point_index}")
            label = f"{name} {suffix}".strip()
            out.append(SnapTarget(label, i, cp.point_index, cp.x, cp.y))
    return out


def fuzzy_filter(targets: list[SnapTarget], query: str) -> list[SnapTarget]:
    """Subsequence fuzzy match (like fzf): query chars must appear in order.

    Ranks by: shorter gaps / earlier match first, then shorter label. Spaces
    in the query are ignored so "r3end2" and "r3 end 2" both match "R3 end 2".
    """
    q = query.lower().replace(" ", "")
    if not q:
        return list(targets)
    scored: list[tuple[int, int, SnapTarget]] = []
    for t in targets:
        hay = t.label.lower().replace(" ", "")
        score = _subseq_score(q, hay)
        if score is not None:
            scored.append((score, len(hay), t))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [t for _s, _l, t in scored]


def _subseq_score(query: str, hay: str) -> int | None:
    """Return a gap-based score if query is a subsequence of hay, else None.
    Lower is better (0 = contiguous match starting at index 0)."""
    qi = 0
    last = -1
    gaps = 0
    for qi_char in query:
        found = hay.find(qi_char, last + 1)
        if found == -1:
            return None
        if last != -1:
            gaps += found - last - 1
        else:
            gaps += found  # leading offset
        last = found
    return gaps
