"""Tests for the connectivity graph (foundation of the keyboard tree editor).

All pure/headless — no GTK needed.
"""

from __future__ import annotations

from pydiylc import (
    Project,
    VeroBoard,
    PerfBoard,
    Resistor,
    SolderPad,
    HookupWire,
    CopperTrace,
    TransistorTO92,
    OpenJack1_4,
)
from pydiylc.graph import (
    build_graph,
    control_points_of,
    components_on_board,
    EdgeType,
)


def test_control_points_two_pin():
    r = Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5)
    pts = control_points_of(r, 0)
    assert len(pts) == 2
    assert (pts[0].x, pts[0].y) == (1.0, 1.0)
    assert (pts[1].x, pts[1].y) == (1.0, 1.5)


def test_control_points_points_list():
    w = HookupWire("W1", points=[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)])
    pts = control_points_of(w, 0)
    assert len(pts) == 4


def test_control_points_multi_node():
    q = TransistorTO92("Q1", x=2.0, y=2.0)
    pts = control_points_of(q, 0)
    assert len(pts) == 3  # E/B/C


def test_control_points_single_anchor():
    pad = SolderPad("P1", x=1.0, y=2.0)
    pts = control_points_of(pad, 0)
    assert len(pts) == 1
    assert (pts[0].x, pts[0].y) == (1.0, 2.0)


def test_junction_clusters_coincident_points():
    p = Project()
    # R1's lower end and a solder pad share (1.0, 1.5)
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    p.add(SolderPad("P1", x=1.0, y=1.5))
    g = build_graph(p)
    j = g.junction_at(1.0, 1.5)
    assert j is not None
    assert j.shared
    assert set(g.components_touching(j)) == {0, 1}


def test_distinct_points_are_separate_junctions():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=2.0, y=2.0))
    g = build_graph(p)
    assert g.junction_at(1.0, 1.0) is not None
    assert g.junction_at(2.0, 2.0) is not None
    assert not g.junction_at(1.0, 1.0).shared


def test_tolerance_merges_near_coincident():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=1.0005, y=1.0))  # within default 0.001 tol
    g = build_graph(p)
    j = g.junction_at(1.0, 1.0)
    assert j is not None
    assert j.shared  # merged into one junction


def test_wire_endpoints_are_wire_edges():
    p = Project()
    p.add(HookupWire("W1", points=[(0.0, 0.0), (1.0, 0.0)]))
    g = build_graph(p)
    types = {e.edge_type for e in g.edges if e.component_index == 0}
    assert types == {EdgeType.WIRE}


def test_board_corners_are_rigid():
    p = Project()
    p.add(VeroBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    g = build_graph(p)
    types = {e.edge_type for e in g.edges if e.component_index == 0}
    assert types == {EdgeType.RIGID}


def test_component_on_board_is_mounted():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    p.add(Resistor("R1", x1=1.5, y1=1.4, x2=1.5, y2=1.6))  # inside the board
    g = build_graph(p)
    r_edges = [e for e in g.edges if e.component_index == 1]
    assert all(e.edge_type is EdgeType.MOUNT for e in r_edges)
    assert all(e.board_index == 0 for e in r_edges)
    assert components_on_board(g, 0) == [1]


def test_component_off_board_is_rigid_not_mounted():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=2.0))
    p.add(OpenJack1_4("J1", x=5.0, y=5.0))  # well outside the board
    g = build_graph(p)
    j_edges = [e for e in g.edges if e.component_index == 1]
    assert all(e.edge_type is EdgeType.RIGID for e in j_edges)
    assert components_on_board(g, 0) == []


def test_partial_mount_only_inside_points():
    """A two-pin part straddling a board edge: only the inside point mounts."""
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=2.0))
    # x1,y1 inside; x2,y2 outside
    p.add(Resistor("R1", x1=1.5, y1=1.5, x2=5.0, y2=5.0))
    g = build_graph(p)
    r_edges = sorted(
        [e for e in g.edges if e.component_index == 1],
        key=lambda e: e.point_index,
    )
    assert r_edges[0].edge_type is EdgeType.MOUNT
    assert r_edges[1].edge_type is EdgeType.RIGID


def test_empty_project_graph():
    g = build_graph(Project())
    assert g.junctions == []
    assert g.edges == []


def test_full_pedal_graph_smoke():
    """A realistic mixed layout builds without error and finds junctions."""
    p = Project()
    p.add(VeroBoard("Board1", x1=1.0, y1=1.0, x2=2.2, y2=1.7))
    p.add(Resistor("R1", x1=1.5, y1=1.4, x2=1.5, y2=1.6))
    p.add(SolderPad("PadIn", x=1.1, y=1.4))
    p.add(HookupWire("W_in", points=[(0.5, 2.0), (1.1, 1.4)], color="ff0000"))
    g = build_graph(p)
    # The wire endpoint at (1.1, 1.4) coincides with the solder pad.
    j = g.junction_at(1.1, 1.4)
    assert j is not None and j.shared
    # R1 sits on the board → mounted.
    assert 1 in components_on_board(g, 0)
