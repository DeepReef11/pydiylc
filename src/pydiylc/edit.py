"""AST-surgery edit helpers.

Stage 3 of the viewer plan was: drag a component in the GTK viewer and have
the source Python file update. The fragile part is the source rewrite — if
done blindly it can corrupt user code. This module builds the rewrite
*without* applying it, so a viewer can show "R1 would move from
(1.2, 1.4) to (1.5, 1.4) in mybuild.py:23; click Apply to write the change."

Two public functions:

- ``propose_move(path, component_name, new_x, new_y, *, second_point=False)``
  returns a ``MoveProposal`` with the old/new source text — no file is
  written. The viewer renders this as a diff with an [Apply] button.

- ``apply_proposal(proposal)`` writes the new text to disk after the user
  agrees.

Supported edits in v0.1: change ``x=``/``y=`` (single-anchor components) or
``x1=``/``y1=`` (with ``second_point=False``, the default) on a known
component by *name*. The component must be constructed via a positional
or keyword call where ``name`` appears as the first positional argument or
as a ``name=`` keyword.

This is intentionally narrow. Stage 3.5 / 3.6 can extend the surface to
cover rotation, value edits, deletes, and inserts.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MoveProposal:
    """A pending source rewrite for a single component move."""

    path: Path
    component_name: str
    old_text: str
    new_text: str
    line: int  # 1-based line where the change starts
    summary: str  # human-readable "R1.x: 1.2 → 1.5" message

    diff_hunk: list[tuple[str, str]] = field(default_factory=list)
    """Tuples (old_line, new_line) for displaying a side-by-side preview."""


def _format_number(v: float) -> str:
    """Match the kind of number literal users actually write."""
    if isinstance(v, int) or v.is_integer():
        return f"{v:.1f}"
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _find_name_arg(call: ast.Call) -> str | None:
    """Return the literal value of `name=...` (or first positional arg)."""
    if call.args:
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    for kw in call.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            v = kw.value.value
            if isinstance(v, str):
                return v
    return None


def _arg_position_for(call: ast.Call, key: str) -> ast.expr | None:
    """Find the AST node for `key=value` if present as keyword.

    We deliberately don't try to map positional args by index — too
    component-specific and we'd need the catalog. Users almost always
    write coords as keywords in pydiylc-style.
    """
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return None


def _set_keyword(call: ast.Call, key: str, new_node: ast.expr) -> bool:
    for kw in call.keywords:
        if kw.arg == key:
            kw.value = new_node
            return True
    return False


def propose_move(
    path: str | Path,
    component_name: str,
    new_x: float,
    new_y: float,
    *,
    second_point: bool = False,
) -> MoveProposal:
    """Plan a coordinate rewrite for the named component.

    ``second_point=False`` updates ``x=`` / ``y=`` (single-anchor) or
    ``x1=`` / ``y1=`` (two-pin) — whichever the component actually has.
    ``second_point=True`` updates ``x2`` / ``y2`` on two-pin components.

    Raises ``LookupError`` if the named component isn't found. Raises
    ``NotImplementedError`` if the call doesn't use keyword args we can edit
    safely (i.e. coords as positional). The viewer should surface both as
    "can't auto-apply".
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    tree = ast.parse(text)

    target_call: ast.Call | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _find_name_arg(node) == component_name:
            target_call = node
            break
    if target_call is None:
        raise LookupError(
            f"component {component_name!r} not found by name in {p}; "
            "pass name= as a keyword or positional string literal."
        )

    if second_point:
        x_key, y_key = "x2", "y2"
    else:
        # Prefer x/y, fall back to x1/y1.
        x_key, y_key = ("x", "y") if _arg_position_for(target_call, "x") else ("x1", "y1")

    x_node = _arg_position_for(target_call, x_key)
    y_node = _arg_position_for(target_call, y_key)
    if x_node is None or y_node is None:
        raise NotImplementedError(
            f"can't rewrite {component_name!r}: coordinates {x_key}/{y_key} "
            "must be passed as keyword args (e.g. `x=1.0, y=1.5`)."
        )

    old_x = x_node.value if isinstance(x_node, ast.Constant) else None
    old_y = y_node.value if isinstance(y_node, ast.Constant) else None

    new_x_node = ast.Constant(value=float(new_x))
    new_y_node = ast.Constant(value=float(new_y))
    _set_keyword(target_call, x_key, new_x_node)
    _set_keyword(target_call, y_key, new_y_node)

    # Render the changed source. We use ast.unparse (3.9+) and try to
    # preserve the surrounding text by only touching the lines spanning the
    # call. ast.unparse can change formatting, so we do a line-level
    # diff and return both representations for the viewer to display.
    new_full = ast.unparse(tree)

    old_lines = text.splitlines()
    new_lines = new_full.splitlines()
    line_no = target_call.lineno  # 1-based

    summary = (
        f"{component_name}.{x_key}: {old_x!r} → {new_x:g}; "
        f"{component_name}.{y_key}: {old_y!r} → {new_y:g}"
    )

    # Pull a small window of the affected lines for preview.
    win = 3
    a = max(0, line_no - 1 - win)
    b = min(len(old_lines), line_no + win)
    hunk: list[tuple[str, str]] = []
    for old, new in zip(old_lines[a:b], new_lines[a:b]):
        hunk.append((old, new))

    return MoveProposal(
        path=p,
        component_name=component_name,
        old_text=text,
        new_text=new_full + ("\n" if text.endswith("\n") else ""),
        line=line_no,
        summary=summary,
        diff_hunk=hunk,
    )


def apply_proposal(proposal: MoveProposal) -> None:
    """Write the proposed new_text to disk. Caller is responsible for
    backup. The viewer should only call this after user confirmation."""
    proposal.path.write_text(proposal.new_text, encoding="utf-8")
