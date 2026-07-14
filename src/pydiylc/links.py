"""Solder joints: which pin each wire endpoint is actually attached to.

Geometry cannot answer that question, and no rule built purely on coordinates
ever will. Park pad A on top of pad B and a wire endpoint sitting at that
coordinate touches *both* of them — but it is soldered to exactly one, and
which one is a fact about history, not position. A geometric rule has to guess,
and both guesses are wrong in a way the user notices immediately: follow the
pin that moves and A walks off with B's wires; refuse to follow and the wire
you were working on is abandoned on the pad you merely passed over.

So we resolve the joint once, while the layout still says it unambiguously, and
then carry it. A link is:

    (wire name, point index)  ->  name of the rigid component it's soldered to

Endpoints touching nothing rigid are simply absent; they're floating, and they
follow nothing.

The map lives on the Project (``project._solder_links``) rather than in the
viewer, so every caller — GUI, MCP, tests — gets the same answer without having
to thread it through. It is runtime state, not part of the saved file: DIYLC's
format has nowhere to record a joint, so on load we rebuild from geometry,
which is unambiguous for any layout that isn't already stacked.

``refresh`` is the only subtle part. It re-derives links after an edit, but an
endpoint whose established joint is still among the pins it touches *keeps*
that joint. That is what makes overlap survivable: while A sits on B, the wire
remembers whose it was.
"""

from __future__ import annotations

from .core import Project
from .graph import (
    ConnectivityGraph,
    build_graph,
    control_points_of,
    is_wire_like,
)


# (wire name, point index) -> name of the rigid component it is soldered to
SolderLinks = dict[tuple[str, int], str]

_ATTR = "_solder_links"


def _rigid_pins_at(project: Project, x: float, y: float, tol: float) -> list[str]:
    """Names of the non-wire components with a control point at (x, y)."""
    names: list[str] = []
    for i, comp in enumerate(project.components):
        if is_wire_like(comp):
            continue  # a wire never anchors another wire — both ends are elastic
        name = getattr(comp, "name", None)
        if not name:
            continue
        for cp in control_points_of(comp, i):
            if abs(cp.x - x) <= tol and abs(cp.y - y) <= tol:
                names.append(name)
                break
    return names


def refresh(
    project: Project,
    previous: SolderLinks | None = None,
    graph: ConnectivityGraph | None = None,
) -> SolderLinks:
    """Re-derive the solder joints after an edit, preserving established ones.

    An endpoint that still touches the pin it was soldered to keeps that joint,
    even when it now touches others as well — that is how a wire remembers
    whose it is while two parts overlap. An endpoint that has been moved onto a
    different pin is re-soldered to it; one touching nothing rigid is dropped.
    """
    g = graph or build_graph(project)
    tol = g.tolerance
    prev = previous or {}
    links: SolderLinks = {}

    for i, comp in enumerate(project.components):
        if not is_wire_like(comp):
            continue
        wire_name = getattr(comp, "name", None)
        if not wire_name:
            continue
        for cp in control_points_of(comp, i):
            key = (wire_name, cp.point_index)
            candidates = _rigid_pins_at(project, cp.x, cp.y, tol)
            if not candidates:
                continue  # floating end — soldered to nothing
            established = prev.get(key)
            if established in candidates:
                links[key] = established  # the joint we already knew about
            elif len(candidates) == 1:
                links[key] = candidates[0]  # newly soldered on
            else:
                # First contact with several stacked pins at once, and no
                # history to break the tie. Pick deterministically so the
                # choice at least doesn't flip about between edits.
                links[key] = sorted(candidates)[0]
    return links


def get(project: Project) -> SolderLinks:
    """The project's solder joints, derived from geometry on first use."""
    links = getattr(project, _ATTR, None)
    if links is None:
        links = refresh(project)
        setattr(project, _ATTR, links)
    return links


def update(project: Project, graph: ConnectivityGraph | None = None) -> SolderLinks:
    """Re-derive after a geometry change, keeping the joints we already knew."""
    links = refresh(project, get(project), graph)
    setattr(project, _ATTR, links)
    return links


def invalidate(project: Project) -> None:
    """Forget the joints — they'll be re-derived from geometry on next use.

    For when the component list itself changed enough that names may no longer
    mean what they did (a reload, a bulk import).
    """
    if hasattr(project, _ATTR):
        delattr(project, _ATTR)


def soldered_to(project: Project, wire_name: str, point_index: int) -> str | None:
    """The component a given wire endpoint is soldered to, if any."""
    return get(project).get((wire_name, point_index))
