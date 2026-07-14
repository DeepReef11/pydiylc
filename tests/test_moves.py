"""Tests for the move engine (step 2 of the keyboard tree editor).

Verifies the attachment-aware propagation rules. All headless.
"""

from __future__ import annotations

from pydiylc import (
    Project,
    PerfBoard,
    VeroBoard,
    Line,
    Resistor,
    SolderPad,
    HookupWire,
    OpenJack1_4,
    TransistorTO92,
)
from pydiylc.moves import (
    move_component,
    move_components,
    move_node,
    move_node_to,
)


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


def test_moving_a_component_leaves_an_unselected_wire_alone():
    """Touching is not attaching: an unselected wire never follows a move.

    Attachment is the selection, not the geometry — see
    ``test_selected_wire_stretches_off_an_unselected_pin`` for taking it along.
    """
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    # Wire sitting on the pad (1.0, 1.0), running out to (3.0, 1.0).
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))

    move_component(p, 0, 0.0, 0.5)  # move the pad down, on its own

    pad, wire = p.components
    assert (pad.x, pad.y) == (1.0, 1.5)          # pad moved
    assert wire.points == [(1.0, 1.0), (3.0, 1.0)]  # wire stayed behind


def test_selected_wire_stretches_off_an_unselected_pin():
    """Select the pad AND the wire: the wire travels, but stays plugged in.

    W1's far end sits on P2, which the user did not select — that endpoint
    holds its anchor, so the wire stretches instead of unplugging P2.
    """
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=3.0, y=1.0))
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))

    move_components(p, [0, 2], 0.0, 0.5)  # P1 + W1, leaving P2 behind

    p1, p2, wire = p.components
    assert (p1.x, p1.y) == (1.0, 1.5)   # selected pad moved
    assert (p2.x, p2.y) == (3.0, 1.0)   # unselected pad untouched
    assert wire.points[0] == (1.0, 1.5)  # P1 end travelled with it
    assert wire.points[1] == (3.0, 1.0)  # P2 end held its anchor → stretched


def test_selected_wire_with_free_ends_moves_whole():
    """No outside anchor to hold: the whole wire translates."""
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))

    move_components(p, [0, 1], 0.0, 0.5)

    assert p.components[1].points == [(1.0, 1.5), (3.0, 1.5)]


def test_moving_wire_itself_moves_both_ends():
    p = Project()
    p.add(HookupWire("W1", points=[(1.0, 1.0), (3.0, 1.0)]))
    move_component(p, 0, 0.0, 1.0)
    w = p.components[0]
    assert w.points[0] == (1.0, 2.0)
    assert w.points[1] == (3.0, 2.0)


def test_line_parked_on_a_bus_does_not_drag_it_away():
    """A line dropped on top of a bus and moved back leaves the bus alone.

    Both are elastic, so overlapping them is *touching*, not attaching. The
    old rule anchored any coincident point, so the round trip dragged the
    whole bus along under the line — it looked like the bus had vanished.
    """
    p = Project()
    p.add(Line("BUS", points=[(1.0, 1.0), (5.0, 1.0)]))
    p.add(Line("L1", points=[(1.0, 3.0), (5.0, 3.0)]))

    move_component(p, 1, 0.0, -2.0)  # park L1 exactly on top of the bus
    move_component(p, 1, 0.0, 2.0)   # ...and take it back off again

    bus, line = p.components
    assert bus.points == [(1.0, 1.0), (5.0, 1.0)]   # bus never moved
    assert line.points == [(1.0, 3.0), (5.0, 3.0)]  # round trip is a no-op


def test_line_touching_one_bus_end_does_not_deform_it():
    """The partial-overlap case: one shared endpoint must not bend the bus."""
    p = Project()
    p.add(Line("BUS", points=[(1.0, 1.0), (5.0, 1.0)]))
    p.add(Line("L1", points=[(1.0, 3.0), (3.0, 3.0)]))

    move_component(p, 1, 0.0, -2.0)  # L1's left end lands on the bus's left end
    move_component(p, 1, 0.0, 2.0)

    bus = p.components[0]
    assert bus.points == [(1.0, 1.0), (5.0, 1.0)]  # not dragged into a diagonal


def test_wire_endpoints_do_not_anchor_each_other():
    """Two wires sharing a junction: moving one leaves the other in place."""
    p = Project()
    p.add(HookupWire("W1", points=[(1.0, 1.0), (2.0, 1.0)]))
    p.add(HookupWire("W2", points=[(2.0, 1.0), (3.0, 1.0)]))

    move_component(p, 0, 0.0, 1.0)

    assert p.components[0].points == [(1.0, 2.0), (2.0, 2.0)]  # W1 moved
    assert p.components[1].points == [(2.0, 1.0), (3.0, 1.0)]  # W2 stayed put


def test_rotating_a_line_does_not_drag_an_overlapping_bus():
    """Same anchoring rule on the rotate path."""
    from pydiylc.moves import rotate_component

    p = Project()
    p.add(Line("BUS", points=[(1.0, 1.0), (5.0, 1.0)]))
    p.add(HookupWire("W1", points=[(1.0, 1.0), (1.0, 3.0)]))

    rotate_component(p, 0, clockwise=True)  # spin the bus about its centroid

    # The bus rotated; the wire that merely touched its end stayed behind.
    assert p.components[1].points == [(1.0, 1.0), (1.0, 3.0)]


def test_component_dropped_on_a_bus_corner_does_not_stick_to_it():
    """Parking a pad on the bus's endpoint must not weld the two together."""
    p = Project()
    p.add(Line("BUS", points=[(1.0, 1.0), (5.0, 1.0)]))
    p.add(SolderPad("P1", x=1.0, y=1.0))  # sitting exactly on the bus corner

    move_component(p, 1, 2.0, 2.0)  # drag the pad away again

    assert p.components[0].points == [(1.0, 1.0), (5.0, 1.0)]  # bus stayed
    assert (p.components[1].x, p.components[1].y) == (3.0, 3.0)


def test_board_move_carries_its_parts_but_not_an_unselected_wire():
    """Containment still propagates; coincidence does not.

    The pad rides the board because it's mounted *on* it. The wire only
    touches the pad, so it stays — select it to bring it along.
    """
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=3.0, y2=2.0))
    p.add(SolderPad("P1", x=2.0, y=1.5))  # on the board
    p.add(HookupWire("W1", points=[(2.0, 1.5), (6.0, 5.0)]))  # off-board far end

    move_component(p, 0, 1.0, 0.0)  # move board right

    board, pad, wire = p.components
    assert pad.x == 3.0  # pad is mounted on the board → moved with it
    assert wire.points == [(2.0, 1.5), (6.0, 5.0)]  # unselected wire untouched


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


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_rotate_4way_enum_cycles_clockwise():
    from pydiylc.moves import rotate_component

    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=2.0, orientation="DEFAULT"))
    r = rotate_component(p, 0, clockwise=True)
    assert r.kind == "enum"
    assert p.components[0].orientation == "_90"
    rotate_component(p, 0)
    assert p.components[0].orientation == "_180"


def test_rotate_4way_enum_wraps():
    from pydiylc.moves import rotate_component

    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=2.0, orientation="_270"))
    rotate_component(p, 0, clockwise=True)
    assert p.components[0].orientation == "DEFAULT"


def test_rotate_4way_counterclockwise():
    from pydiylc.moves import rotate_component

    p = Project()
    p.add(TransistorTO92("Q1", x=2.0, y=2.0, orientation="DEFAULT"))
    rotate_component(p, 0, clockwise=False)
    assert p.components[0].orientation == "_270"


def test_rotate_hv_enum_toggles():
    from pydiylc.moves import rotate_component
    from pydiylc import MiniToggleSwitch

    p = Project()
    p.add(MiniToggleSwitch("SW1", x=2.0, y=2.0, orientation="VERTICAL"))
    rotate_component(p, 0)
    assert p.components[0].orientation == "HORIZONTAL"
    rotate_component(p, 0)
    assert p.components[0].orientation == "VERTICAL"


def test_rotate_two_pin_rotates_coords():
    from pydiylc.moves import rotate_component

    p = Project()
    # Horizontal resistor centered at (1.5, 1.0), endpoints (1.0,1.0)-(2.0,1.0)
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=2.0, y2=1.0))
    rotate_component(p, 0, clockwise=True)
    r = p.components[0]
    # After 90° CW about centroid (1.5, 1.0): becomes vertical.
    assert r.x1 == r.x2 == 1.5
    assert {r.y1, r.y2} == {0.5, 1.5}


def test_rotate_coords_clean_floats():
    from pydiylc.moves import rotate_component

    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.3, y2=1.0))
    rotate_component(p, 0)
    r = p.components[0]
    for v in (r.x1, r.y1, r.x2, r.y2):
        # No long binary tails.
        assert len(repr(v).split(".")[-1]) <= 4
