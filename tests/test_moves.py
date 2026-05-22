"""Tests for the move engine (step 2 of the keyboard tree editor).

Verifies the attachment-aware propagation rules. All headless.
"""

from __future__ import annotations

from pydiylc import (
    Project,
    PerfBoard,
    VeroBoard,
    Resistor,
    SolderPad,
    HookupWire,
    OpenJack1_4,
    TransistorTO92,
)
from pydiylc.moves import move_component, move_node, move_node_to


# ---------------------------------------------------------------------------
# Whole-component moves
# ---------------------------------------------------------------------------


def test_move_free_component_translates_all_points():
    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    move_component(p, 0, 0.5, 0.25)
    r = p.components[0]
    assert (r.x1, r.y1) == (1.5, 1.25)
    assert (r.x2, r.y2) == (1.5, 1.75)


def test_move_single_anchor_component():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=2.0))
    move_component(p, 0, -0.5, 0.5)
    assert (p.components[0].x, p.components[0].y) == (0.5, 2.5)


def test_board_move_drags_mounted_components():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    p.add(Resistor("R1", x1=1.5, y1=1.4, x2=1.5, y2=1.6))  # on the board
    p.add(SolderPad("P1", x=2.0, y=1.5))                    # on the board
    p.add(OpenJack1_4("J1", x=8.0, y=8.0))                  # off the board

    move_component(p, 0, 1.0, 0.0)  # move the board right by 1 inch

    board, r, pad, jack = p.components
    # Board moved.
    assert board.x1 == 2.0 and board.x2 == 4.0
    # Mounted components moved with it.
    assert r.x1 == 2.5 and r.x2 == 2.5
    assert pad.x == 3.0
    # Off-board jack stayed put.
    assert jack.x == 8.0


def test_moving_component_stretches_attached_wire():
    """A wire endpoint coincident with a moved component follows; far end stays."""
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    # Wire from the pad (1.0, 1.0) out to (3.0, 1.0)
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))

    move_component(p, 0, 0.0, 0.5)  # move the pad down

    pad, wire = p.components
    assert (pad.x, pad.y) == (1.0, 1.5)
    # Near endpoint followed the pad; far endpoint unchanged → wire stretched.
    assert wire.points[0] == (1.0, 1.5)
    assert wire.points[1] == (3.0, 1.0)


def test_moving_wire_itself_moves_both_ends():
    p = Project()
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))
    move_component(p, 0, 0.0, 1.0)
    w = p.components[0]
    assert w.points[0] == (1.0, 2.0)
    assert w.points[1] == (3.0, 2.0)


def test_board_move_stretches_boundary_crossing_wire():
    """A wire with one end on a mounted pad and the other off-board stretches."""
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    p.add(SolderPad("P1", x=2.0, y=1.5))  # on the board
    p.add(HookupWire("W1", points=[(2.0, 1.5), (6.0, 5.0)]))  # off-board far end

    move_component(p, 0, 1.0, 0.0)  # move board right

    board, pad, wire = p.components
    assert pad.x == 3.0  # pad moved with board
    assert wire.points[0] == (3.0, 1.5)  # near end followed
    assert wire.points[1] == (6.0, 5.0)  # far end stayed → stretched


def test_multi_node_component_moves_as_body():
    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=2.0))
    before = p.components[0]._control_points()
    move_component(p, 0, 0.5, 0.5)
    after = p.components[0]._control_points()
    # Every pin shifted by the same delta.
    for (bx, by), (ax, ay) in zip(before, after):
        assert abs((ax - bx) - 0.5) < 1e-6
        assert abs((ay - by) - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Node-level moves
# ---------------------------------------------------------------------------


def test_move_node_shifts_one_endpoint_only():
    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    move_node(p, 0, 1, 0.5, 0.0)  # move only the second endpoint
    r = p.components[0]
    assert (r.x1, r.y1) == (1.0, 1.0)   # first end unchanged
    assert (r.x2, r.y2) == (1.5, 1.5)   # second end moved


def test_move_node_detaches_from_junction():
    """Node-level move leaves coincident points on other components behind."""
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))
    # Move the wire's near endpoint away — the pad should NOT follow.
    move_node(p, 1, 0, 0.0, 1.0)
    pad, wire = p.components
    assert (pad.x, pad.y) == (1.0, 1.0)        # pad stayed
    assert wire.points[0] == (1.0, 2.0)        # only the wire end moved


def test_move_node_to_absolute():
    p = Project()
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))
    move_node_to(p, 0, 1, 5.0, 2.0)
    assert p.components[0].points[1] == (5.0, 2.0)


def test_move_node_bad_index_raises():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    import pytest

    with pytest.raises(IndexError):
        move_node(p, 0, 5, 1.0, 1.0)


def test_move_result_reports_shifts():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    p.add(Resistor("R1", x1=1.5, y1=1.4, x2=1.5, y2=1.6))
    res = move_component(p, 0, 1.0, 0.0)
    moved = res.components_moved()
    assert 0 in moved and 1 in moved  # board + mounted resistor


def test_move_results_are_grid_clean():
    """Moves must not introduce float noise."""
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    move_component(p, 0, 0.1, 0.2)
    pad = p.components[0]
    # 1.0 + 0.1 in binary is 1.1 only after rounding; assert clean repr.
    assert repr(pad.x) == "1.1"
    assert repr(pad.y) == "1.2"
