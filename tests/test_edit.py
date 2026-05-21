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


def test_diff_hunk_lines_pair_old_and_new(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='Pad1', x=1.0, y=2.0))
    """)
    proposal = propose_move(p, "Pad1", new_x=3.5, new_y=4.0)
    assert any("1.0" in old and "3.5" in new for old, new in proposal.diff_hunk)
