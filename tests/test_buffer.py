"""Tests for the working-buffer save flow (headless)."""

from __future__ import annotations

import textwrap

import pytest

from pydiylc import BlankBoard, Resistor, SolderPad
from pydiylc.buffer import Buffer
from pydiylc.edit import MoveOp


def _write(tmp_path, src: str):
    p = tmp_path / "layout.py"
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


def test_from_disk_loads_text(tmp_path):
    p = _write(tmp_path, "x = 1\n")
    buf = Buffer.from_disk(p)
    assert buf.text == "x = 1\n"
    assert buf.disk_text == buf.text
    assert not buf.is_dirty


def test_propose_against_buffer_not_disk(tmp_path):
    """A second edit must build on the first in-buffer edit, not on stale disk."""
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(p)
    # First edit: add a BlankBoard in-buffer.
    prop1 = buf.propose(adds=[BlankBoard("B1", x1=2.0, y1=2.0, x2=3.0, y2=2.7)])
    assert prop1 is not None
    buf.apply(prop1)
    assert buf.is_dirty
    # Second edit: move P1. Crucially, B1 must STILL be in the buffer
    # afterwards — this is the bug the buffer model fixes.
    prop2 = buf.propose(moves=[MoveOp("P1", 5.0, 5.0)])
    buf.apply(prop2)
    assert "B1" in buf.text
    assert "x=5.0" in buf.text
    # Disk is unchanged — flush hasn't run.
    assert "B1" not in p.read_text()


def test_propose_empty_returns_none(tmp_path):
    p = _write(tmp_path, "x = 1\n")
    buf = Buffer.from_disk(p)
    assert buf.propose() is None


def test_flush_writes_buffer_to_disk(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(p)
    prop = buf.propose(adds=[Resistor("R1", x1=2.0, y1=2.0, x2=2.0, y2=2.5)])
    buf.apply(prop)
    assert buf.is_dirty
    assert buf.flush() is True
    assert not buf.is_dirty
    assert "R1" in p.read_text()


def test_flush_noop_when_clean(tmp_path):
    p = _write(tmp_path, "x = 1\n")
    buf = Buffer.from_disk(p)
    assert buf.flush() is False
    assert p.read_text() == "x = 1\n"


def test_discard_reverts_buffer_to_disk(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(p)
    prop = buf.propose(adds=[Resistor("R1", x1=2.0, y1=2.0, x2=2.0, y2=2.5)])
    buf.apply(prop)
    assert buf.is_dirty
    buf.discard()
    assert not buf.is_dirty
    assert "R1" not in buf.text


def test_diff_vs_disk_renders(tmp_path):
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(p)
    buf.text = buf.text.replace("x=1.0", "x=5.0")
    diff = buf.diff_vs_disk()
    assert "x=1.0" in diff and "x=5.0" in diff
    assert diff.startswith("---")  # unified diff header


def test_temp_file_is_cleaned_up(tmp_path):
    """propose() creates a temp file in the source dir; it must be removed."""
    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(p)
    before = set(tmp_path.iterdir())
    buf.propose(adds=[Resistor("R1", x1=2, y1=2, x2=2, y2=2.5)])
    after = set(tmp_path.iterdir())
    assert before == after  # no leftover .py-buf- files


def test_buffer_propose_handles_keyword_op(tmp_path):
    """Buffer.propose(keyword_ops=[...]) should write back via temp file."""
    from pydiylc.edit import KeywordOp

    p = _write(tmp_path, """
        from pydiylc import Project, TransistorTO92
        def build():
            pr = Project()
            pr.add(TransistorTO92(name='Q1', x=1.0, y=1.0, orientation='DEFAULT'))
            return pr
    """)
    buf = Buffer.from_disk(p)
    proposal = buf.propose(keyword_ops=[KeywordOp("Q1", "orientation", "_90")])
    assert proposal is not None
    buf.apply(proposal)
    assert "orientation='_90'" in buf.text or 'orientation="_90"' in buf.text


def test_buffer_propose_handles_delete_op(tmp_path):
    from pydiylc.edit import DeleteOp

    p = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            pr.add(SolderPad(name='P2', x=2.0, y=2.0))
            return pr
    """)
    buf = Buffer.from_disk(p)
    proposal = buf.propose(deletes=[DeleteOp("P1")])
    buf.apply(proposal)
    assert "P1" not in buf.text
    assert "P2" in buf.text


def test_buffer_propose_handles_coords_op(tmp_path):
    from pydiylc.edit import CoordsOp

    p = _write(tmp_path, """
        from pydiylc import Project, Resistor
        def build():
            pr = Project()
            pr.add(Resistor(name='R1', x1=1.0, y1=1.0, x2=2.0, y2=1.0))
            return pr
    """)
    buf = Buffer.from_disk(p)
    proposal = buf.propose(coords_ops=[CoordsOp("R1", two_pin=(1.5, 0.5, 1.5, 1.5))])
    buf.apply(proposal)
    assert "x1=1.5" in buf.text and "y2=1.5" in buf.text


def test_refresh_disk_after_self_write(tmp_path):
    """After writing our buffer to disk, refresh_disk re-syncs disk_text so
    a subsequent watcher poll doesn't see the file as 'externally changed'."""
    p = _write(tmp_path, "a = 1\n")
    buf = Buffer.from_disk(p)
    buf.text = "a = 2\n"
    p.write_text(buf.text)  # simulate our own save bypassing flush()
    buf.refresh_disk()
    assert buf.disk_text == "a = 2\n"
    assert not buf.is_dirty
