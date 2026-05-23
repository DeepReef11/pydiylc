"""Tests for the AST-surgery edit module (stage 3 viewer foundation)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pydiylc.edit import propose_move, apply_proposal


def _write(tmp_path: Path, src: str) -> Path:
    p = tmp_path / "layout.py"
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


def test_propose_move_returns_summary(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        def build():
            p = Project()
            p.add(Resistor('R1', 1.0, 1.0, 1.0, 1.5, value='10K'))
            return p
    """)
    # x1/y1 don't appear as kwargs in this file → not editable yet
    with pytest.raises(NotImplementedError):
        propose_move(p, "R1", new_x=2.0, new_y=2.0)


def test_positional_coords_error_is_actionable(tmp_path):
    """The 'can't move' message should name the constructor and suggest kwargs."""
    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor('R1', 1.0, 1.0, 1.0, 1.5, value='10K'))
    """)
    with pytest.raises(NotImplementedError) as ei:
        propose_move(p, "R1", new_x=2.0, new_y=2.0)
    msg = str(ei.value)
    assert "Resistor" in msg
    assert "positional" in msg
    assert "name=" in msg  # suggests the fix


def test_grid_snap_floats_are_clean(tmp_path):
    """Grid-snapped coordinates must not leak binary-float noise (2.4000...004)."""
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    noisy = round(2.4 / 0.1) * 0.1  # = 2.4000000000000004
    assert repr(noisy) != "2.4"  # confirm the input really is noisy
    proposal = propose_move(p, "P1", new_x=5.0, new_y=noisy)
    assert "2.4000000000000004" not in proposal.new_text
    assert "y=2.4" in proposal.new_text


def test_propose_move_single_anchor(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='Pad1', x=1.0, y=2.0))
    """)
    proposal = propose_move(p, "Pad1", new_x=3.5, new_y=4.0)
    assert "Pad1" in proposal.summary
    assert "3.5" in proposal.summary
    assert "x=3.5" in proposal.new_text
    assert "y=4.0" in proposal.new_text
    # original file untouched
    assert "x=1.0" in p.read_text()


def test_propose_move_two_pin_kwargs(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor(name='R1', x1=1.0, y1=1.0, x2=1.0, y2=1.5, value='10K'))
    """)
    proposal = propose_move(p, "R1", new_x=2.0, new_y=2.5)
    assert "x1=2.0" in proposal.new_text
    assert "y1=2.5" in proposal.new_text


def test_second_point_edit(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor(name='R1', x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    """)
    proposal = propose_move(p, "R1", new_x=2.0, new_y=2.5, second_point=True)
    assert "x2=2.0" in proposal.new_text
    assert "y2=2.5" in proposal.new_text


def test_unknown_component_raises(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='Pad1', x=1.0, y=2.0))
    """)
    with pytest.raises(LookupError, match="Nonexistent"):
        propose_move(p, "Nonexistent", new_x=1, new_y=1)


def test_apply_writes_to_disk(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='Pad1', x=1.0, y=2.0))
    """)
    proposal = propose_move(p, "Pad1", new_x=3.5, new_y=4.0)
    apply_proposal(proposal)
    after = p.read_text()
    assert "x=3.5" in after
    assert "y=4.0" in after


def test_move_component_inplace_single_anchor():
    from pydiylc import SolderPad
    from pydiylc.edit import move_component_inplace

    pad = SolderPad("P1", x=1.0, y=2.0)
    move_component_inplace(pad, 0.5, -0.25)
    assert pad.x == 1.5 and pad.y == 1.75


def test_move_component_inplace_two_pin():
    from pydiylc import Resistor
    from pydiylc.edit import move_component_inplace

    r = Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5)
    move_component_inplace(r, 0.5, 0.5)
    assert (r.x1, r.y1, r.x2, r.y2) == (1.5, 1.5, 1.5, 2.0)


def test_move_component_inplace_points_list():
    from pydiylc import CopperTrace
    from pydiylc.edit import move_component_inplace

    t = CopperTrace("T1", points=[(0.0, 0.0), (1.0, 0.0)])
    move_component_inplace(t, 1.0, 2.0)
    assert t.points == [(1.0, 2.0), (2.0, 2.0)]


def test_diff_hunk_carries_line_numbers(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='Pad1', x=1.0, y=2.0))
    """)
    proposal = propose_move(p, "Pad1", new_x=3.5, new_y=4.0)
    # Each entry is (line_no, old, new); the changed line should mention both
    # the old and new x value, and carry a plausible 1-based line number.
    changed = [(n, o, nw) for (n, o, nw) in proposal.diff_hunk if o != nw]
    assert changed, "expected at least one changed line"
    line_no, old, new = changed[0]
    assert isinstance(line_no, int) and line_no >= 1
    assert "1.0" in old and "3.5" in new


def test_locate_component_returns_line_and_context(tmp_path):
    """locate_component finds a positional-coord component without rewriting it."""
    from pydiylc.edit import locate_component

    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor('R1', 1.0, 1.0, 1.0, 1.5, value='10K'))
    """)
    loc = locate_component(p, "R1")
    assert loc.component_name == "R1"
    assert loc.line >= 1
    # The constructor line must be in the context window, flagged by its number.
    nums = [n for n, _src in loc.context]
    assert loc.line in nums
    assert "Resistor" in loc.reason
    # The context line at loc.line should contain the actual call.
    focus_src = next(src for n, src in loc.context if n == loc.line)
    assert "Resistor" in focus_src


def test_locate_component_not_found(tmp_path):
    from pydiylc.edit import locate_component

    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor('R1', 1.0, 1.0, 1.0, 1.5))
    """)
    with pytest.raises(LookupError, match="Nope"):
        locate_component(p, "Nope")


def test_propose_point_move_rewrites_one_entry(tmp_path):
    from pydiylc.edit import propose_point_move

    p = _write(tmp_path, """
        from pydiylc import Project, HookupWire
        project = Project()
        project.add(HookupWire(name='W1', points=[(0.5, 2.0), (1.1, 1.4)], color='ff0000'))
    """)
    proposal = propose_point_move(p, "W1", point_index=1, new_x=3.0, new_y=4.0)
    assert "(3.0, 4.0)" in proposal.new_text
    # The other point is untouched.
    assert "(0.5, 2.0)" in proposal.new_text
    assert "points[1]" in proposal.summary


def test_propose_point_move_first_entry(tmp_path):
    from pydiylc.edit import propose_point_move

    p = _write(tmp_path, """
        from pydiylc import Project, CopperTrace
        project = Project()
        project.add(CopperTrace(name='T1', points=[(1.0, 1.0), (2.0, 1.0)]))
    """)
    proposal = propose_point_move(p, "T1", point_index=0, new_x=1.5, new_y=1.5)
    assert "(1.5, 1.5)" in proposal.new_text
    assert "(2.0, 1.0)" in proposal.new_text


def test_propose_point_move_index_out_of_range(tmp_path):
    from pydiylc.edit import propose_point_move

    p = _write(tmp_path, """
        from pydiylc import Project, CopperTrace
        project = Project()
        project.add(CopperTrace(name='T1', points=[(1.0, 1.0), (2.0, 1.0)]))
    """)
    with pytest.raises(NotImplementedError, match="out of range"):
        propose_point_move(p, "T1", point_index=9, new_x=0, new_y=0)


def test_propose_point_move_no_points_kwarg(tmp_path):
    from pydiylc.edit import propose_point_move

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    with pytest.raises(NotImplementedError, match="points="):
        propose_point_move(p, "P1", point_index=0, new_x=2.0, new_y=2.0)


def test_propose_point_move_clean_floats(tmp_path):
    from pydiylc.edit import propose_point_move

    p = _write(tmp_path, """
        from pydiylc import Project, HookupWire
        project = Project()
        project.add(HookupWire(name='W1', points=[(0.5, 2.0), (1.1, 1.4)]))
    """)
    noisy = round(2.4 / 0.1) * 0.1
    proposal = propose_point_move(p, "W1", point_index=0, new_x=1.0, new_y=noisy)
    assert "2.4000000000000004" not in proposal.new_text
    assert "2.4" in proposal.new_text


def test_propose_add_appends_new_line(tmp_path):
    from pydiylc.edit import propose_add
    from pydiylc import SolderPad

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    proposal = propose_add(p, SolderPad("P2", x=2.0, y=3.0))
    # Both pads should be present in the new source.
    assert "P1" in proposal.new_text
    assert "P2" in proposal.new_text
    # The new call should mention the type, name, and coords.
    assert "SolderPad" in proposal.new_text
    assert "name='P2'" in proposal.new_text or 'name="P2"' in proposal.new_text
    assert "x=2.0" in proposal.new_text
    assert "y=3.0" in proposal.new_text


def test_propose_add_inside_build_function(tmp_path):
    """An add inside def build(): finds the right insertion site."""
    from pydiylc.edit import propose_add
    from pydiylc import SolderPad

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            p = Project()
            p.add(SolderPad(name='P1', x=1.0, y=1.0))
            return p
    """)
    proposal = propose_add(p, SolderPad("P2", x=2.0, y=3.0))
    assert "P2" in proposal.new_text
    # Order is preserved: P1 still comes before P2.
    assert proposal.new_text.index("'P1'") < proposal.new_text.index("'P2'")


def test_propose_add_no_anchor_raises(tmp_path):
    """A file with no existing .add(...) call can't be auto-inserted."""
    from pydiylc.edit import propose_add
    from pydiylc import SolderPad

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
    """)
    with pytest.raises(NotImplementedError, match="no existing"):
        propose_add(p, SolderPad("P1", x=0.0, y=0.0))


def test_propose_add_round_trips_through_loader(tmp_path):
    """The inserted line must be valid Python and produce the right component."""
    import importlib.util
    from pydiylc.edit import propose_add, apply_proposal
    from pydiylc import Resistor

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad, Resistor
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            return pr
    """)
    new = Resistor("R1", x1=2.0, y1=2.0, x2=2.0, y2=2.5, value="10K")
    proposal = propose_add(p, new)
    apply_proposal(proposal)
    # Reload the rewritten module and check both components are there.
    spec = importlib.util.spec_from_file_location("rewritten", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    project = mod.build()
    names = [c.name for c in project.components]
    assert names == ["P1", "R1"]
    r = project.components[1]
    assert isinstance(r, Resistor)
    assert r.value == "10K"
    assert (r.x1, r.y1, r.x2, r.y2) == (2.0, 2.0, 2.0, 2.5)


def test_propose_add_clean_floats(tmp_path):
    from pydiylc.edit import propose_add
    from pydiylc import SolderPad

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    noisy = round(2.4 / 0.1) * 0.1
    proposal = propose_add(p, SolderPad("P2", x=noisy, y=1.0))
    assert "2.4000000000000004" not in proposal.new_text
    assert "x=2.4" in proposal.new_text


def test_propose_add_appends_missing_import(tmp_path):
    """Adding a component whose class isn't imported must extend the import line."""
    import importlib.util
    from pydiylc.edit import propose_add, apply_proposal
    from pydiylc import BlankBoard

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    proposal = propose_add(p, BlankBoard("B1", x1=2.0, y1=2.0, x2=3.0, y2=2.7))
    # BlankBoard must show up in the import list.
    assert "BlankBoard" in proposal.new_text
    # The rewritten file must actually be importable (the original bug).
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rewritten", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # must not raise NameError


def test_propose_add_skips_import_when_already_present(tmp_path):
    """Adding a Resistor when Resistor is already imported doesn't duplicate."""
    from pydiylc.edit import propose_add
    from pydiylc import Resistor

    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor(name='R1', x1=0, y1=0, x2=0, y2=0.5))
    """)
    proposal = propose_add(p, Resistor("R2", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    # Only one "Resistor" mention in the import list — count it on the
    # import line, not the call lines.
    import_line = next(
        ln for ln in proposal.new_text.splitlines()
        if ln.startswith("from pydiylc import")
    )
    assert import_line.count("Resistor") == 1


def test_propose_add_star_import_no_op(tmp_path):
    """A star import already covers any name; we don't extend it."""
    from pydiylc.edit import propose_add
    from pydiylc import BlankBoard

    p = _write(tmp_path, """
        from pydiylc import *
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    proposal = propose_add(p, BlankBoard("B1", x1=2.0, y1=2.0, x2=3.0, y2=2.7))
    # Still a single star import — we didn't add a parallel named import.
    import_lines = [
        ln for ln in proposal.new_text.splitlines()
        if ln.startswith("from pydiylc import")
    ]
    assert import_lines == ["from pydiylc import *"]


def test_propose_changes_bundles_move_and_adds(tmp_path):
    """A move + an uncommitted add must produce ONE rewrite containing both."""
    import importlib.util
    from pydiylc.edit import propose_changes, MoveOp, apply_proposal
    from pydiylc import BlankBoard

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            return pr
    """)
    proposal = propose_changes(
        p,
        moves=[MoveOp("P1", 5.0, 5.0)],
        adds=[BlankBoard("B1", x1=2.0, y1=2.0, x2=3.0, y2=2.7)],
    )
    text = proposal.new_text
    # The move took effect…
    assert "x=5.0" in text and "y=5.0" in text
    # …AND the new component is present (the previously-lost-on-commit bug).
    assert "B1" in text
    assert "BlankBoard" in text  # both in import line and in the call
    # And the rewritten file actually imports cleanly with both parts.
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rewritten", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    project = mod.build()
    names = [c.name for c in project.components]
    assert "P1" in names and "B1" in names


def test_propose_changes_empty_raises():
    from pydiylc.edit import propose_changes
    import pytest

    with pytest.raises(NotImplementedError, match="nothing to do"):
        propose_changes("/tmp/whatever.py")


def test_propose_changes_lookup_error_on_missing_move(tmp_path):
    from pydiylc.edit import propose_changes, MoveOp
    import pytest

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    with pytest.raises(LookupError):
        propose_changes(p, moves=[MoveOp("Nope", 0, 0)])


def test_propose_changes_keyword_op_writes_orientation(tmp_path):
    """Rotation of an oriented part should write the new orientation back."""
    import importlib.util
    from pydiylc.edit import propose_changes, KeywordOp, apply_proposal

    p = _write(tmp_path, """
        from pydiylc import Project, TransistorTO92
        def build():
            pr = Project()
            pr.add(TransistorTO92(name='Q1', x=1.0, y=1.0, orientation='DEFAULT'))
            return pr
    """)
    proposal = propose_changes(p, keyword_ops=[KeywordOp("Q1", "orientation", "_90")])
    assert "orientation='_90'" in proposal.new_text or 'orientation="_90"' in proposal.new_text
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rt", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.build().components[0].orientation == "_90"


def test_propose_changes_keyword_op_appends_when_missing(tmp_path):
    """A keyword_op for a kwarg not yet on the call should append it."""
    from pydiylc.edit import propose_changes, KeywordOp

    p = _write(tmp_path, """
        from pydiylc import Project, TransistorTO92
        project = Project()
        project.add(TransistorTO92(name='Q1', x=1.0, y=1.0))
    """)
    proposal = propose_changes(p, keyword_ops=[KeywordOp("Q1", "orientation", "_180")])
    assert "orientation='_180'" in proposal.new_text or 'orientation="_180"' in proposal.new_text


def test_propose_changes_coords_op_two_pin(tmp_path):
    """Coordinate rotation: replace all four coords in one shot."""
    from pydiylc.edit import propose_changes, CoordsOp

    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        project = Project()
        project.add(Resistor(name='R1', x1=1.0, y1=1.0, x2=2.0, y2=1.0))
    """)
    proposal = propose_changes(p, coords_ops=[CoordsOp("R1", two_pin=(1.5, 0.5, 1.5, 1.5))])
    text = proposal.new_text
    assert "x1=1.5" in text and "y1=0.5" in text
    assert "x2=1.5" in text and "y2=1.5" in text


def test_propose_changes_delete_op_removes_line(tmp_path):
    """A DeleteOp removes the matching `<x>.add(...)` line."""
    import importlib.util
    from pydiylc.edit import propose_changes, DeleteOp, apply_proposal

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            pr.add(SolderPad(name='P2', x=2.0, y=2.0))
            return pr
    """)
    proposal = propose_changes(p, deletes=[DeleteOp("P1")])
    assert "P2" in proposal.new_text
    assert "P1" not in proposal.new_text
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rt", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = [c.name for c in mod.build().components]
    assert names == ["P2"]


def test_propose_changes_delete_missing_raises(tmp_path):
    from pydiylc.edit import propose_changes, DeleteOp
    import pytest

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    with pytest.raises(LookupError):
        propose_changes(p, deletes=[DeleteOp("Nope")])


def test_propose_changes_bundles_rotate_and_delete(tmp_path):
    """A keyword_op + a delete in one proposal applies cleanly."""
    import importlib.util
    from pydiylc.edit import propose_changes, KeywordOp, DeleteOp, apply_proposal

    p = _write(tmp_path, """
        from pydiylc import Project, TransistorTO92, SolderPad
        def build():
            pr = Project()
            pr.add(TransistorTO92(name='Q1', x=1.0, y=1.0, orientation='DEFAULT'))
            pr.add(SolderPad(name='P_extra', x=2.0, y=2.0))
            return pr
    """)
    proposal = propose_changes(
        p,
        keyword_ops=[KeywordOp("Q1", "orientation", "_90")],
        deletes=[DeleteOp("P_extra")],
    )
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rt", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    proj = mod.build()
    assert [c.name for c in proj.components] == ["Q1"]
    assert proj.components[0].orientation == "_90"


def test_propose_changes_adds_only_no_move(tmp_path):
    """`adds=[...]` with no moves still produces a valid proposal."""
    import importlib.util
    from pydiylc.edit import propose_changes, apply_proposal
    from pydiylc import Resistor

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            return pr
    """)
    proposal = propose_changes(p, adds=[Resistor("R1", x1=2, y1=2, x2=2, y2=2.5)])
    apply_proposal(proposal)
    spec = importlib.util.spec_from_file_location("rt", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = [c.name for c in mod.build().components]
    assert names == ["P1", "R1"]


def test_propose_add_inserts_import_when_missing(tmp_path):
    """A file with no pydiylc import at all gets one inserted."""
    from pydiylc.edit import propose_add
    from pydiylc import Project, Resistor

    p = _write(tmp_path, '''
        """A layout."""
        import pydiylc
        project = pydiylc.Project()
        project.add(pydiylc.SolderPad(name='P1', x=1.0, y=1.0))
    ''')
    proposal = propose_add(p, Resistor("R1", x1=0, y1=0, x2=0, y2=0.5))
    assert "from pydiylc import Resistor" in proposal.new_text
