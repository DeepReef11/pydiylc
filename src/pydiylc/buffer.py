"""Working-buffer model for the viewer's save flow.

Replaces the old "every Apply dialog re-parses the disk file" model with a
single mutable in-memory copy of the source text. Every edit (move, rotate,
add, delete) is applied to the buffer immediately; ``flush()`` writes it to
disk in one go (driven by ``Enter`` / ``Ctrl+S`` in the UI, gated by a
save-dialog preference).

This eliminates the stale-source race — a chain of in-memory edits no
longer has to reconcile with what's on disk at commit time, because the
buffer *is* the intended source.

Pure and headless. The viewer's save dialog and watcher pause logic live in
``viewer.py`` and call into this.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from .edit import MoveProposal, propose_changes


@dataclass
class Buffer:
    """An editable copy of a Python layout source.

    ``text`` is the working content. ``disk_text`` is what's on disk at the
    last known sync point. ``is_dirty`` is True when the two diverge.
    """

    path: Path
    text: str
    disk_text: str

    @classmethod
    def from_disk(cls, path: str | Path) -> "Buffer":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        return cls(p, text, text)

    @property
    def is_dirty(self) -> bool:
        return self.text != self.disk_text

    def diff_vs_disk(self, context: int = 3) -> str:
        """Unified diff between disk_text and the current buffer text."""
        if not self.is_dirty:
            return ""
        diff = difflib.unified_diff(
            self.disk_text.splitlines(keepends=True),
            self.text.splitlines(keepends=True),
            fromfile=f"{self.path.name} (disk)",
            tofile=f"{self.path.name} (buffer)",
            n=context,
        )
        return "".join(diff)

    def apply(self, proposal: MoveProposal) -> None:
        """Replace the buffer with the rewrite text from a MoveProposal.

        The proposal must have been built against ``self.text`` (the current
        buffer), not against disk — otherwise pending in-buffer edits would
        be silently dropped. Callers should use ``propose()`` which handles
        this.
        """
        self.text = proposal.new_text

    def propose(self, *, moves=(), adds=()) -> MoveProposal | None:
        """Build a MoveProposal against the *buffer* (not disk).

        Returns None if there's nothing to do. The returned proposal's
        ``new_text`` is what the buffer would become; the caller applies it
        with ``apply()`` (no dialog needed for buffer edits — the dialog is
        the *save* dialog, run separately at flush time).
        """
        if not moves and not adds:
            return None
        # propose_changes reads from disk. We need it to operate on the
        # buffer text. Write the buffer to a virtual location: easiest is a
        # temp file that propose_changes can read from. Cleaner: refactor
        # propose_changes to accept text, but that's a bigger surgery — for
        # now we round-trip via a temp file in the same directory so file
        # encoding/newline behavior matches.
        import tempfile, os

        # Use a temp file beside the real one so paths in errors look right.
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.path.stem}-buf-", suffix=".py", dir=str(self.path.parent),
        )
        os.close(fd)
        temp = Path(temp_path)
        try:
            temp.write_text(self.text, encoding="utf-8")
            proposal = propose_changes(temp, moves=moves, adds=adds)
            # Rewrite the proposal's path back to the real file for display.
            return MoveProposal(
                path=self.path,
                component_name=proposal.component_name,
                old_text=self.text,
                new_text=proposal.new_text,
                line=proposal.line,
                summary=proposal.summary,
                diff_hunk=proposal.diff_hunk,
            )
        finally:
            try:
                temp.unlink()
            except OSError:
                pass

    def flush(self) -> bool:
        """Write the buffer to disk. Returns True if anything was written.

        After a successful flush, ``disk_text`` is updated so the buffer is
        no longer dirty.
        """
        if not self.is_dirty:
            return False
        self.path.write_text(self.text, encoding="utf-8")
        self.disk_text = self.text
        return True

    def discard(self) -> None:
        """Revert the buffer to whatever's on disk right now (re-read)."""
        self.text = self.path.read_text(encoding="utf-8")
        self.disk_text = self.text

    def refresh_disk(self) -> None:
        """Update ``disk_text`` from the file without touching the buffer.

        Use after an external write to disk that we want to *acknowledge*
        but not adopt — e.g. a save we just performed ourselves.
        """
        self.disk_text = self.path.read_text(encoding="utf-8")
