"""End-to-end integration test for the working-buffer save flow.

Drives the headless logic the viewer's tree-mode would drive, without GTK:
load a layout, mutate the buffer + project together through several ops,
flush, re-import the rewritten file, and assert the saved state matches
the in-memory project.

This is the test that would catch a "your N-action session saves but the
reload doesn't match what was on screen" regression.
"""

from __future__ import annotations

import importlib.util
import textwrap
import warnings
from pathlib import Path

from pydiylc import (
    Project,
    SolderPad,
    Resistor,
    TransistorTO92,
    HookupWire,
)
from pydiylc.buffer import Buffer
from pydiylc.edit import MoveOp, KeywordOp, CoordsOp, DeleteOp
from pydiylc import moves, tree_editor


def _write(tmp_path: Path, src: str) -> Path:
    p = tmp_path / "layout.py"
    p.write_text(textwrap.dedent(src).lstrip(), encoding="utf-8")
    return p


def _reimport(path: Path):
    """Fresh import of a rewritten .py layout → its Project."""
    spec = importlib.util.spec_from_file_location("rt", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build()


def test_full_edit_session_round_trip(tmp_path):
    """One session: move + add + rotate + delete → save → reimport matches."""
    src = _write(tmp_path, """
        from pydiylc import Project, SolderPad, Resistor, TransistorTO92
        def build():
            pr = Project(title='session', width_cm=15, height_cm=10)
            pr.add(SolderPad(name='P1', x=1.0, y=1.0))
            pr.add(SolderPad(name='P2', x=2.0, y=2.0))
            pr.add(Resistor(name='R1', x1=1.5, y1=1.5, x2=1.5, y2=2.0))
            pr.add(TransistorTO92(name='Q1', x=3.0, y=3.0, orientation='DEFAULT'))
            return pr
    """)

    # Load just like the viewer does.
    spec = importlib.util.spec_from_file_location("orig", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    project = mod.build()
    buf = Buffer.from_disk(src)

    def sync(**kw):
        prop = buf.propose(**kw)
        if prop is not None:
            buf.apply(prop)

    # 1) Move P1 to (5.0, 5.0). In-memory + buffer.
    moves.move_component(project, 0, dx=4.0, dy=4.0)
    sync(moves=[MoveOp("P1", project.components[0].x, project.components[0].y)])

    # 2) Add a HookupWire.
    new_wire = tree_editor.make_wire("W_new", (5.0, 5.0), (2.0, 2.0))
    project.add(new_wire)
    sync(adds=[new_wire])

    # 3) Rotate Q1 → orientation='_90'.
    moves.rotate_component(project, 3, clockwise=True)
    sync(keyword_ops=[KeywordOp("Q1", "orientation", project.components[3].orientation)])

    # 4) Delete P2.
    name = "P2"
    project.components.pop(1)  # P2 was at index 1
    sync(deletes=[DeleteOp(name)])

    # Flush to disk and re-import.
    assert buf.is_dirty
    buf.flush()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        re_project = _reimport(src)

    # In-memory and re-imported component lists should agree.
    in_mem = [(type(c).__name__, getattr(c, "name", None)) for c in project.components]
    on_disk = [(type(c).__name__, getattr(c, "name", None)) for c in re_project.components]
    assert in_mem == on_disk, f"\nin-memory: {in_mem}\non-disk:   {on_disk}"

    # P1 must be at its post-move position on disk.
    p1 = next(c for c in re_project.components if c.name == "P1")
    assert (p1.x, p1.y) == (5.0, 5.0)

    # Q1's orientation must be the post-rotate value on disk.
    q1 = next(c for c in re_project.components if c.name == "Q1")
    assert q1.orientation == "_90"

    # W_new must exist with the wire endpoints.
    w = next(c for c in re_project.components if c.name == "W_new")
    assert isinstance(w, HookupWire)
    assert w.points[0] == (5.0, 5.0)

    # P2 must be gone.
    assert all(c.name != "P2" for c in re_project.components)


def test_no_changes_means_clean_buffer_no_write(tmp_path):
    """A no-op session shouldn't dirty the buffer."""
    src = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        project = Project()
        project.add(SolderPad(name='P1', x=1.0, y=1.0))
    """)
    buf = Buffer.from_disk(src)
    assert not buf.is_dirty
    # Empty propose returns None — no buffer churn.
    assert buf.propose() is None
    assert not buf.is_dirty
    assert buf.flush() is False  # nothing to write


def test_chained_moves_accumulate_in_buffer(tmp_path):
    """Successive in-buffer edits build on each other (the stale-source fix)."""
    src = _write(tmp_path, """
        from pydiylc import Project, SolderPad
        def build():
            pr = Project()
            pr.add(SolderPad(name='P1', x=0.0, y=0.0))
            return pr
    """)
    buf = Buffer.from_disk(src)
    # Move 1.
    buf.apply(buf.propose(moves=[MoveOp("P1", 1.0, 1.0)]))
    # Move 2 — must build on Move 1's result, not on stale disk.
    buf.apply(buf.propose(moves=[MoveOp("P1", 5.0, 5.0)]))
    buf.flush()
    re_project = _reimport(src)
    assert (re_project.components[0].x, re_project.components[0].y) == (5.0, 5.0)
