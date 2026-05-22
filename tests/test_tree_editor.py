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


def test_empty_project_nav_is_safe():
    nav = NavState(build_tree(Project()))
    assert nav.current is None
    nav.next_component()  # no crash
    nav.first_node()
    nav.next_node()
    assert nav.current is None
