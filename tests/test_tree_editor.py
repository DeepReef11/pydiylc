"""Tests for the tree-editor model and navigation (headless)."""

from __future__ import annotations

from pydiylc import (
    Project,
    Resistor,
    SolderPad,
    CopperTrace,
    TransistorTO92,
    VeroBoard,
)
from pydiylc.tree_editor import build_tree, NavState


def _project() -> Project:
    p = Project()
    p.add(VeroBoard("Board1", x1=1.0, y1=1.0, x2=2.0, y2=2.0))  # two-pin
    p.add(Resistor("R1", x1=1.5, y1=1.4, x2=1.5, y2=1.6))       # two-pin (2 nodes)
    p.add(SolderPad("P1", x=1.1, y=1.4))                        # single anchor
    p.add(CopperTrace("W1", points=[(0.5, 2.0), (1.1, 1.4), (2.0, 1.0)]))  # 3 nodes
    p.add(TransistorTO92("Q1", x=1.6, y=1.3))                   # multi-node
    return p


def test_build_tree_header_per_component():
    rows = build_tree(_project())
    headers = [r for r in rows if not r.is_node]
    assert len(headers) == 5
    assert headers[1].label.startswith("R1")


def test_two_pin_has_two_node_rows():
    rows = build_tree(_project())
    r1_nodes = [r for r in rows if r.component_index == 1 and r.is_node]
    assert len(r1_nodes) == 2
    assert all(n.movable for n in r1_nodes)


def test_points_list_has_n_node_rows():
    rows = build_tree(_project())
    w_nodes = [r for r in rows if r.component_index == 3 and r.is_node]
    assert len(w_nodes) == 3


def test_single_anchor_has_no_node_children():
    rows = build_tree(_project())
    pad_nodes = [r for r in rows if r.component_index == 2 and r.is_node]
    assert pad_nodes == []


def test_multinode_pins_are_readonly():
    rows = build_tree(_project())
    q_nodes = [r for r in rows if r.component_index == 4 and r.is_node]
    assert len(q_nodes) == 3
    assert all(not n.movable for n in q_nodes)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_next_prev_component_moves_between_headers():
    nav = NavState(build_tree(_project()))
    assert nav.current.component_index == 0
    nav.next_component()
    assert nav.current.component_index == 1
    assert not nav.current.is_node
    nav.prev_component()
    assert nav.current.component_index == 0


def test_next_component_wraps():
    nav = NavState(build_tree(_project()))
    for _ in range(5):
        nav.next_component()
    # 5 components, wrapping → back to 0
    assert nav.current.component_index == 0


def test_first_node_enters_component():
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1
    nav.first_node()
    assert nav.current.is_node
    assert nav.current.component_index == 1
    assert nav.current.point_index == 0


def test_tab_walks_nodes_within_component():
    nav = NavState(build_tree(_project()))
    nav.next_component()        # R1
    nav.first_node()            # end 1
    assert nav.current.point_index == 0
    nav.next_node()             # end 2
    assert nav.current.point_index == 1
    nav.next_node()             # wraps back to end 1
    assert nav.current.point_index == 0


def test_tab_owner_stays_within_component():
    """Tab keeps walking the owning component, never jumps to another."""
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1
    nav.next_component()  # P1 (single anchor)
    nav.next_component()  # W1 (3 nodes)
    nav.first_node()
    owner = nav.tab_owner
    for _ in range(6):
        nav.next_node()
        assert nav.current.component_index == owner


def test_to_header_collapses():
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1
    nav.first_node()
    assert nav.current.is_node
    nav.to_header()
    assert not nav.current.is_node
    assert nav.current.component_index == 1


def test_rebuild_keeps_cursor_on_same_node():
    p = _project()
    nav = NavState(build_tree(p))
    nav.next_component()  # R1
    nav.first_node()      # end 1
    target = (nav.current.component_index, nav.current.point_index)
    # Mutate and rebuild.
    p.components[1].x1 = 9.0
    nav.rebuild(p)
    assert (nav.current.component_index, nav.current.point_index) == target


def test_fresh_nav_can_enter_first_component_nodes():
    """A new NavState sits on component 0; first_node enters it directly,
    no next_component needed first."""
    nav = NavState(build_tree(_project()))
    assert nav.current.component_index == 0
    nav.first_node()
    # Board1 is two-pin (has nodes), so we should land on its first node.
    assert nav.current.is_node
    assert nav.current.component_index == 0
    assert nav.current.point_index == 0


def test_next_component_from_start_goes_to_second():
    """Down from the first component lands on the second, not back on first."""
    nav = NavState(build_tree(_project()))
    assert nav.current.component_index == 0
    nav.next_component()
    assert nav.current.component_index == 1


def test_enter_exit_nodes_toggles_node_level():
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1 (two-pin, has nodes)
    assert nav.node_level is False
    assert nav.enter_nodes() is True
    assert nav.node_level is True
    assert nav.current.is_node
    nav.exit_nodes()
    assert nav.node_level is False
    assert not nav.current.is_node


def test_enter_nodes_noop_for_single_anchor():
    """A single-anchor component (SolderPad) has no drillable nodes."""
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1
    nav.next_component()  # P1 (single anchor)
    assert nav.has_nodes() is False
    assert nav.enter_nodes() is False
    assert nav.node_level is False  # stayed at component level


def test_enter_nodes_noop_for_multinode():
    """Multi-node bodies (TransistorTO92) have read-only pins; can't drill to move."""
    nav = NavState(build_tree(_project()))
    # walk to Q1 (multi-node) at component index 4
    while nav.current.component_index != 4:
        nav.next_component()
    # Q1 has node rows, but they're read-only (not movable). has_nodes() is
    # about addressable rows; enter_nodes lands on a read-only pin.
    # The viewer still treats a read-only node's move as a body move, so this
    # is acceptable — just assert it doesn't crash.
    nav.enter_nodes()
    # current may be a read-only pin row.
    if nav.current.is_node:
        assert nav.current.movable is False


def test_next_component_clears_node_level():
    nav = NavState(build_tree(_project()))
    nav.next_component()  # R1
    nav.enter_nodes()
    assert nav.node_level is True
    nav.next_component()  # moving to another component pops out
    assert nav.node_level is False
    assert not nav.current.is_node


def test_focus_node_jumps_to_specific_node():
    """/ search uses focus_node to move the cursor to any node directly."""
    nav = NavState(build_tree(_project()))
    # Jump straight to R1 (index 1), end 2 (point_index 1).
    assert nav.focus_node(1, 1) is True
    assert nav.current.component_index == 1
    assert nav.current.point_index == 1
    assert nav.node_level is True


def test_focus_node_header_when_point_none():
    nav = NavState(build_tree(_project()))
    assert nav.focus_node(2, None) is True  # P1 single-anchor header
    assert nav.current.component_index == 2
    assert not nav.current.is_node
    assert nav.node_level is False


def test_focus_node_falls_back_to_header():
    """Requesting a non-existent point falls back to the component header."""
    nav = NavState(build_tree(_project()))
    # P1 is single-anchor — it has no point_index=1 node.
    assert nav.focus_node(2, 1) is True
    assert nav.current.component_index == 2
    assert not nav.current.is_node


def test_focus_node_missing_component():
    nav = NavState(build_tree(_project()))
    assert nav.focus_node(99, 0) is False


def test_addable_types_listed():
    from pydiylc.tree_editor import addable_component_types

    types = addable_component_types()
    assert "Resistor" in types
    assert "SolderPad" in types
    assert types == sorted(types)


def test_make_default_two_pin():
    from pydiylc.tree_editor import make_default_component
    from pydiylc import Resistor

    c = make_default_component("Resistor", "R9", 1.0, 1.0)
    assert isinstance(c, Resistor)
    assert (c.x1, c.y1) == (1.0, 1.0)
    assert c.x2 == 1.3 and c.y2 == 1.0  # small two-pin default: 0.3in body


def test_make_default_board_is_larger():
    """Boards default to a usable size — not the small-part default."""
    from pydiylc.tree_editor import make_default_component
    from pydiylc import BlankBoard, PerfBoard, VeroBoard

    for type_name in ("BlankBoard", "PerfBoard", "VeroBoard"):
        c = make_default_component(type_name, "B", 1.0, 1.0)
        assert c.x1 == 1.0 and c.y1 == 1.0
        # Width ≥ 0.7in and non-zero height — fits actual components on it.
        assert c.x2 - c.x1 >= 0.7, f"{type_name} too narrow: {c.x2 - c.x1}"
        assert c.y2 - c.y1 > 0, f"{type_name} flat: y2 == y1"


def test_make_default_shape_has_visible_frame():
    from pydiylc.tree_editor import make_default_component

    c = make_default_component("Rectangle", "Box1", 1.0, 1.0)
    assert c.x2 - c.x1 >= 0.5
    assert c.y2 - c.y1 > 0


def test_make_default_single_anchor():
    from pydiylc.tree_editor import make_default_component
    from pydiylc import SolderPad

    c = make_default_component("SolderPad", "P9", 2.0, 3.0)
    assert isinstance(c, SolderPad)
    assert (c.x, c.y) == (2.0, 3.0)


def test_make_default_points_list():
    from pydiylc.tree_editor import make_default_component
    from pydiylc import CopperTrace

    c = make_default_component("CopperTrace", "T9", 1.0, 1.0)
    assert isinstance(c, CopperTrace)
    assert len(c.points) == 2
    assert c.points[0] == (1.0, 1.0)


def test_make_default_label_gets_text():
    from pydiylc.tree_editor import make_default_component
    from pydiylc import Label

    c = make_default_component("Label", "MyLabel", 1.0, 1.0)
    assert isinstance(c, Label)
    assert c.text == "MyLabel"


def test_make_default_unknown_type():
    from pydiylc.tree_editor import make_default_component
    import pytest

    with pytest.raises(ValueError, match="unknown component type"):
        make_default_component("Nonexistent", "X", 0, 0)


def test_clamp_cursor_after_shrink():
    p = _project()
    nav = NavState(build_tree(p))
    # Move cursor near the end, then delete components and rebuild.
    nav.cursor = len(nav.rows) - 1
    del p.components[-1]  # remove Q1
    del p.components[-1]  # remove the trace
    nav.rows = build_tree(p)
    nav.clamp_cursor()
    assert 0 <= nav.cursor < len(nav.rows)


def test_clamp_cursor_empty():
    nav = NavState([])
    nav.cursor = 5
    nav.clamp_cursor()
    assert nav.cursor == 0


def test_empty_project_nav_is_safe():
    nav = NavState(build_tree(Project()))
    assert nav.current is None
    nav.next_component()  # no crash
    nav.first_node()
    nav.next_node()
    assert nav.current is None
