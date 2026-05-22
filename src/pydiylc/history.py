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

from .core import Project


DEFAULT_LIMIT = 100


@dataclass
class History:
    project: Project
    limit: int = DEFAULT_LIMIT
    _stack: list[list] = field(default_factory=list)

    def record(self, label: str = "") -> None:
        """Snapshot the current component list before a mutating action.

        ``label`` is optional and only for debugging / status display.
        """
        snapshot = (label, copy.deepcopy(self.project.components))
        self._stack.append(snapshot)
        if len(self._stack) > self.limit:
            # Drop the oldest so memory stays bounded.
            self._stack.pop(0)

    def can_undo(self) -> bool:
        return bool(self._stack)

    def undo(self) -> bool:
        """Restore the most recent snapshot. Returns False if nothing to undo.

        The restored components replace the project's list in place so any
        callers holding a reference to ``project`` see the change.
        """
        if not self._stack:
            return False
        _label, components = self._stack.pop()
        self.project.components[:] = components
        return True

    def last_label(self) -> str | None:
        if not self._stack:
            return None
        return self._stack[-1][0] or None

    def depth(self) -> int:
        return len(self._stack)

    def clear(self) -> None:
        self._stack.clear()
