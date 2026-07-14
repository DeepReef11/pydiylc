"""Undo history for in-memory project edits.

A small snapshot-based stack: before any mutating action (move, rotate, add,
remove), the caller calls ``record()`` to push a deep copy of the project's
component list. ``undo()`` pops the last snapshot and restores it.

Pure and headless — the viewer drives it. Snapshots are bounded so a long
editing session doesn't grow without limit.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

from .core import Project


DEFAULT_LIMIT = 100


@dataclass
class History:
    """Undo + redo snapshot stack.

    The model is the standard one editors use: a new ``record()`` clears the
    redo stack (you've branched away from any "future"), an ``undo()`` pops
    the most recent snapshot onto the redo stack so ``redo()`` can put it
    back, and ``redo()`` does the inverse. Snapshots are bounded.
    """

    project: Project
    limit: int = DEFAULT_LIMIT
    # Optional extra-state hooks. The viewer snapshots its working buffer
    # text through these, so undo/redo revert the buffer together with the
    # components — otherwise Enter would save the edit you just undid.
    capture_extra: Callable[[], Any] | None = None
    restore_extra: Callable[[Any], None] | None = None
    _stack: list[tuple[str, list, dict, Any]] = field(default_factory=list)
    _redo: list[tuple[str, list, dict, Any]] = field(default_factory=list)

    # Project-level fields captured alongside the component list, so that
    # metadata edits (title, canvas size, ...) are undoable too.
    _META_FIELDS = (
        "title", "author", "width_cm", "height_cm", "grid_inches",
        "dot_spacing",
    )

    def _meta(self) -> dict:
        return {k: getattr(self.project, k) for k in self._META_FIELDS}

    def _restore_meta(self, meta: dict) -> None:
        for k, v in meta.items():
            setattr(self.project, k, v)

    def _extra(self) -> Any:
        return self.capture_extra() if self.capture_extra is not None else None

    def _put_extra(self, extra: Any) -> None:
        if self.restore_extra is not None:
            self.restore_extra(extra)

    def record(self, label: str = "") -> None:
        """Snapshot the component list + project metadata before a mutating
        action.

        Clears the redo stack — a fresh edit means any "future" you'd undone
        back from is now off the timeline.
        """
        snapshot = (
            label, copy.deepcopy(self.project.components), self._meta(),
            self._extra(),
        )
        self._stack.append(snapshot)
        if len(self._stack) > self.limit:
            self._stack.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._stack)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        """Restore the most recent snapshot. Pushes the current state onto
        the redo stack so ``redo()`` can put it back. Returns False when
        there's nothing to undo."""
        if not self._stack:
            return False
        label, components, meta, extra = self._stack.pop()
        # Capture what we're about to undo *from* so redo can come back here.
        self._redo.append(
            (label, copy.deepcopy(self.project.components), self._meta(),
             self._extra())
        )
        if len(self._redo) > self.limit:
            self._redo.pop(0)
        self.project.components[:] = components
        self._restore_meta(meta)
        self._put_extra(extra)
        return True

    def redo(self) -> bool:
        """Reapply the most recently undone snapshot. Pushes the current
        state back onto the undo stack so ``undo()`` can revert again.
        Returns False when there's nothing to redo."""
        if not self._redo:
            return False
        label, components, meta, extra = self._redo.pop()
        self._stack.append(
            (label, copy.deepcopy(self.project.components), self._meta(),
             self._extra())
        )
        if len(self._stack) > self.limit:
            self._stack.pop(0)
        self.project.components[:] = components
        self._restore_meta(meta)
        self._put_extra(extra)
        return True

    def last_label(self) -> str | None:
        if not self._stack:
            return None
        return self._stack[-1][0] or None

    def depth(self) -> int:
        return len(self._stack)

    def redo_depth(self) -> int:
        return len(self._redo)

    def clear(self) -> None:
        self._stack.clear()
        self._redo.clear()
