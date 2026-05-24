"""Project-mutation helpers for align + snap-to-grid.

The MCP server and the GTK viewer both want these operations; this
module is the single source of truth so neither one drifts from the
other.

All functions mutate the project in place and return a small report
suitable for both the MCP tool's JSON reply and the viewer's
status-bar feedback.
"""

from __future__ import annotations

from typing import Iterable

from .core import Project
from . import moves


def snap_to_grid(
    project: Project,
    names: Iterable[str] | None = None,
    grid: float = 0.1,
) -> dict:
    """Snap component control points to ``grid`` increments.

    With ``names=None``, snaps every component in the project. Otherwise
    only the named components are touched. Returns
    ``{"snapped": N, "components": [names]}``.
    """
    from .graph import control_points_of

    if names is None:
        indices = list(range(len(project.components)))
    else:
        name_set = set(names)
        indices = [
            i for i, c in enumerate(project.components)
            if getattr(c, "name", None) in name_set
        ]

    def _snap(v: float) -> float:
        return round(v / grid) * grid

    plan: list[tuple[int, int, float, float]] = []
    for idx in indices:
        c = project.components[idx]
        for cp in control_points_of(c, idx):
            nx, ny = _snap(cp.x), _snap(cp.y)
            if abs(nx - cp.x) > 1e-9 or abs(ny - cp.y) > 1e-9:
                plan.append((idx, cp.point_index, nx, ny))

    touched: set[int] = set()
    for (idx, pi, nx, ny) in plan:
        cur = control_points_of(project.components[idx], idx)
        cp = next((x for x in cur if x.point_index == pi), None)
        if cp is None:
            continue
        dx, dy = nx - cp.x, ny - cp.y
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            moves.move_node(project, idx, pi, dx, dy)
            touched.add(idx)
    return {
        "snapped": len(plan),
        "components": [
            getattr(project.components[i], "name", None)
            for i in sorted(touched)
        ],
    }


def align(
    project: Project,
    names: list[str],
    axis: str = "x",
    mode: str = "first",
) -> dict:
    """Align named components on an axis (``'x'`` or ``'y'``).

    ``mode`` is one of ``'first'`` (anchor = first-named coord),
    ``'mean'`` (centroid), ``'min'``, or ``'max'``. Each component's
    centroid drives the comparison; the whole component then shifts.

    Returns ``{"aligned": N, "components": [names]}``.
    """
    from .graph import control_points_of

    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    if mode not in ("first", "mean", "min", "max"):
        raise ValueError("mode must be one of: first, mean, min, max")
    if len(names) < 2:
        raise ValueError("align needs at least 2 component names")

    by_name = {getattr(c, "name", None): i for i, c in enumerate(project.components)}
    targets: list[tuple[int, float, float]] = []
    for nm in names:
        i = by_name.get(nm)
        if i is None:
            continue
        cps = list(control_points_of(project.components[i], i))
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

    moved: list[int] = []
    for (i, cx, cy) in targets:
        cur = cx if axis == "x" else cy
        d = anchor - cur
        if abs(d) > 1e-9:
            dx, dy = (d, 0.0) if axis == "x" else (0.0, d)
            moves.move_component(project, i, dx, dy)
            moved.append(i)
    return {
        "aligned": len(moved),
        "components": [
            getattr(project.components[i], "name", None) for i in moved
        ],
    }
