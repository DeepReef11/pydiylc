"""Tests for the undo history (headless)."""

from __future__ import annotations

from pydiylc import Project, Resistor, SolderPad
from pydiylc.history import History
from pydiylc import moves


def test_record_and_undo_restores_position():
    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    h = History(p)

    h.record("move")
    moves.move_component(p, 0, 1.0, 0.0)
    assert p.components[0].x1 == 2.0

    assert h.undo() is True
    assert p.components[0].x1 == 1.0


def test_undo_removes_added_component():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    h = History(p)

    h.record("add")
    p.add(SolderPad("P2", x=2.0, y=2.0))
    assert len(p.components) == 2

    h.undo()
    assert len(p.components) == 1
    assert p.components[0].name == "P1"


def test_undo_restores_removed_component():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=2.0, y=2.0))
    h = History(p)

    h.record("remove")
    del p.components[1]
    assert len(p.components) == 1

    h.undo()
    assert len(p.components) == 2
    assert p.components[1].name == "P2"


def test_multiple_undos_in_lifo_order():
    p = Project()
    p.add(Resistor("R1", x1=0.0, y1=0.0, x2=0.0, y2=0.5))
    h = History(p)

    h.record(); moves.move_component(p, 0, 1.0, 0.0)  # x1 -> 1.0
    h.record(); moves.move_component(p, 0, 1.0, 0.0)  # x1 -> 2.0
    assert p.components[0].x1 == 2.0

    h.undo()
    assert p.components[0].x1 == 1.0
    h.undo()
    assert p.components[0].x1 == 0.0


def test_undo_empty_returns_false():
    p = Project()
    h = History(p)
    assert h.can_undo() is False
    assert h.undo() is False


def test_snapshot_is_isolated_deep_copy():
    """Mutating live components must not change the stored snapshot."""
    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    h = History(p)
    h.record()
    p.components[0].x1 = 99.0
    h.undo()
    assert p.components[0].x1 == 1.0


def test_limit_bounds_stack():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p, limit=3)
    for _ in range(10):
        h.record()
    assert h.depth() == 3


def test_label_tracked():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p)
    h.record("rotate Q1")
    assert h.last_label() == "rotate Q1"


def test_clear():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p)
    h.record()
    h.clear()
    assert not h.can_undo()


# ---------------------------------------------------------------------------
# Redo
# ---------------------------------------------------------------------------


def test_redo_after_undo_restores_state():
    p = Project()
    p.add(Resistor("R1", x1=0.0, y1=0.0, x2=0.0, y2=0.5))
    h = History(p)

    h.record(); moves.move_component(p, 0, 1.0, 0.0)  # x1 -> 1.0
    assert p.components[0].x1 == 1.0

    h.undo()  # back to 0.0
    assert p.components[0].x1 == 0.0
    assert h.can_redo()

    h.redo()  # forward to 1.0 again
    assert p.components[0].x1 == 1.0


def test_redo_when_empty_returns_false():
    p = Project()
    h = History(p)
    assert h.can_redo() is False
    assert h.redo() is False


def test_record_clears_redo_stack():
    """A fresh edit clears anything still on the redo stack — branching off."""
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p)
    h.record(); p.components[0].x = 1.0
    h.undo()
    assert h.can_redo()
    # A new edit clears the redo branch.
    h.record(); p.components[0].x = 5.0
    assert not h.can_redo()


def test_multiple_undo_redo_cycles():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p)
    for x in (1.0, 2.0, 3.0):
        h.record()
        p.components[0].x = x
    # Undo twice → x is 1.0
    h.undo(); h.undo()
    assert p.components[0].x == 1.0
    # Redo twice → x is 3.0 again
    h.redo(); h.redo()
    assert p.components[0].x == 3.0


def test_redo_depth_reports_remaining_redos():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    h = History(p)
    h.record(); p.components[0].x = 1.0
    h.record(); p.components[0].x = 2.0
    assert h.redo_depth() == 0
    h.undo(); h.undo()
    assert h.redo_depth() == 2
    h.redo()
    assert h.redo_depth() == 1
