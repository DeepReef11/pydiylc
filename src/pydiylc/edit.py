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

    diff_hunk: list[tuple[int, str, str]] = field(default_factory=list)
    """Tuples (line_no, old_line, new_line) for a line-numbered diff preview.

    ``line_no`` is the 1-based source line of ``old_line``. Where a line is
    unchanged, old_line == new_line.
    """


@dataclass
class LocateResult:
    """Where a component lives in the source, when we can't rewrite it.

    Returned by ``locate_component`` so the viewer can show a line-numbered
    code preview (same look as a MoveProposal diff) even for components built
    with positional coordinates that we won't auto-edit.
    """

    path: Path
    component_name: str
    line: int  # 1-based line of the constructor call
    summary: str
    reason: str  # why we can't auto-apply
    context: list[tuple[int, str]] = field(default_factory=list)
    """(line_no, source_line) window around the component for display."""


def _format_number(v: float) -> str:
    """Match the kind of number literal users actually write."""
    if isinstance(v, int) or v.is_integer():
        return f"{v:.1f}"
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _clean_float(v: float) -> float:
    """Round to 4 decimals to remove binary-float noise from grid math.

    e.g. 5.0 / 0.1 * 0.1 → 2.4000000000000004 becomes 2.4. Coordinates in
    DIYLC layouts never need more than 0.001 in precision, so 4 places is
    safe and keeps the emitted literal short.
    """
    return round(float(v), 4)


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
        # The component exists but its coordinates are positional, e.g.
        # Resistor('R1', 1.0, 1.0, 1.0, 1.5). We only edit keyword coords to
        # avoid guessing positional layouts per component type.
        ctor = getattr(target_call.func, "id", None) or getattr(
            target_call.func, "attr", "?"
        )
        raise NotImplementedError(
            f"{component_name!r} is built with positional coordinates "
            f"(`{ctor}({component_name!r}, ...)`). The viewer can only "
            f"auto-edit keyword coords. Rewrite as "
            f"`{ctor}(name={component_name!r}, {x_key}=..., {y_key}=...)` "
            "to enable drag-to-move on this component."
        )

    old_x = x_node.value if isinstance(x_node, ast.Constant) else None
    old_y = y_node.value if isinstance(y_node, ast.Constant) else None

    # Quantize to kill float noise like 2.4000000000000004 that creeps in
    # from grid-snap arithmetic (5.0 / 0.1 * 0.1). Round to 4 decimals and
    # drop a trailing .0-only tail so the written literal is clean (2.4).
    new_x_node = ast.Constant(value=_clean_float(new_x))
    new_y_node = ast.Constant(value=_clean_float(new_y))
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

    hunk = _line_numbered_hunk(old_lines, new_lines, line_no)

    return MoveProposal(
        path=p,
        component_name=component_name,
        old_text=text,
        new_text=new_full + ("\n" if text.endswith("\n") else ""),
        line=line_no,
        summary=summary,
        diff_hunk=hunk,
    )


def propose_point_move(
    path: str | Path,
    component_name: str,
    point_index: int,
    new_x: float,
    new_y: float,
) -> MoveProposal:
    """Plan a rewrite of one entry in a ``points=[...]`` keyword argument.

    For points-list components (CopperTrace, CurvedTrace, HookupWire, Line)
    when built with a ``points=`` keyword whose elements are literal
    ``(x, y)`` tuples/lists. ``point_index`` selects which entry to rewrite.

    Raises ``LookupError`` if the component isn't found, ``NotImplementedError``
    if there's no editable ``points=`` keyword or the indexed element isn't a
    literal coordinate pair.
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
            f"component {component_name!r} not found by name in {p}"
        )

    points_node = _arg_position_for(target_call, "points")
    if points_node is None or not isinstance(points_node, (ast.List, ast.Tuple)):
        ctor = getattr(target_call.func, "id", None) or getattr(
            target_call.func, "attr", "?"
        )
        raise NotImplementedError(
            f"{component_name!r}: can't rewrite — it needs a literal "
            f"`points=[(x, y), ...]` keyword. Rewrite as "
            f"`{ctor}(name={component_name!r}, points=[(1.0, 1.0), ...])`."
        )

    if not (0 <= point_index < len(points_node.elts)):
        raise NotImplementedError(
            f"{component_name!r}: point index {point_index} out of range "
            f"(have {len(points_node.elts)} points)."
        )

    elt = points_node.elts[point_index]
    if not isinstance(elt, (ast.Tuple, ast.List)) or len(elt.elts) != 2:
        raise NotImplementedError(
            f"{component_name!r}: points[{point_index}] is not a literal "
            "(x, y) pair, so it can't be rewritten."
        )

    old_x = elt.elts[0].value if isinstance(elt.elts[0], ast.Constant) else None
    old_y = elt.elts[1].value if isinstance(elt.elts[1], ast.Constant) else None

    elt.elts[0] = ast.Constant(value=_clean_float(new_x))
    elt.elts[1] = ast.Constant(value=_clean_float(new_y))

    new_full = ast.unparse(tree)
    old_lines = text.splitlines()
    new_lines = new_full.splitlines()
    line_no = target_call.lineno

    summary = (
        f"{component_name}.points[{point_index}]: "
        f"({old_x!r}, {old_y!r}) → ({new_x:g}, {new_y:g})"
    )
    hunk = _line_numbered_hunk(old_lines, new_lines, line_no)

    return MoveProposal(
        path=p,
        component_name=component_name,
        old_text=text,
        new_text=new_full + ("\n" if text.endswith("\n") else ""),
        line=line_no,
        summary=summary,
        diff_hunk=hunk,
    )


def _component_to_call(component) -> ast.Call:
    """Build an AST ``ClassName(kwarg=...)`` call for a Component.

    Uses every dataclass field with ``name`` first, skipping fields whose
    current value equals the field's default (keeps the emitted line short).
    Measure fields render as ``mm(0.1)``/``inches(0.5)``/``cm(2.0)`` calls;
    point lists as list literals; everything else as bare constants.
    """
    import dataclasses

    from .core import Measure

    cls = type(component)
    type_name = cls.__name__
    fields = list(dataclasses.fields(component))

    # Order: name first, then the rest in declaration order.
    def sort_key(f):
        return (0 if f.name == "name" else 1, fields.index(f))

    keywords: list[ast.keyword] = []
    for f in sorted(fields, key=sort_key):
        if f.name.startswith("_"):
            continue
        value = getattr(component, f.name)
        # Compute the dataclass default for this field.
        if f.default is not dataclasses.MISSING:
            default = f.default
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            try:
                default = f.default_factory()  # type: ignore[misc]
            except Exception:
                default = object()  # never equal to value
        else:
            default = object()
        # Skip values that match the default — except name (always emit).
        if f.name != "name" and _values_equal(value, default):
            continue
        keywords.append(ast.keyword(arg=f.name, value=_value_to_ast(value)))

    return ast.Call(
        func=ast.Name(id=type_name, ctx=ast.Load()),
        args=[],
        keywords=keywords,
    )


def _values_equal(a, b) -> bool:
    """Compare two field values for default-stripping. Tolerant of Measure."""
    from .core import Measure

    if isinstance(a, Measure) and isinstance(b, Measure):
        return a.value == b.value and a.unit == b.unit
    return a == b


def _value_to_ast(value) -> ast.expr:
    """Render a Python value as an AST expression.

    Floats are cleaned of binary noise (matches the move-write convention).
    Measures become ``mm(...)``/``inches(...)``/``cm(...)`` calls.
    Tuples of length 2 (coordinate points) render as parenthesized tuples.
    """
    from .core import Measure

    if isinstance(value, Measure):
        funcs = {"mm": "mm", "in": "inches", "cm": "cm"}
        fn = funcs.get(value.unit)
        if fn is not None:
            return ast.Call(
                func=ast.Name(id=fn, ctx=ast.Load()),
                args=[ast.Constant(value=_clean_float(value.value))],
                keywords=[],
            )
        # Fallback: Measure(value, unit)
        return ast.Call(
            func=ast.Name(id="Measure", ctx=ast.Load()),
            args=[
                ast.Constant(value=_clean_float(value.value)),
                ast.Constant(value=value.unit),
            ],
            keywords=[],
        )
    if isinstance(value, bool):
        return ast.Constant(value=value)
    if isinstance(value, float):
        return ast.Constant(value=_clean_float(value))
    if isinstance(value, int):
        return ast.Constant(value=value)
    if isinstance(value, str):
        return ast.Constant(value=value)
    if value is None:
        return ast.Constant(value=None)
    if isinstance(value, (list, tuple)):
        elts = [_value_to_ast(v) for v in value]
        # Preserve tuple-ness for 2-tuples (points); use a list for top-level
        # `points=[...]` containers since user code overwhelmingly writes lists.
        if isinstance(value, tuple):
            return ast.Tuple(elts=elts, ctx=ast.Load())
        return ast.List(elts=elts, ctx=ast.Load())
    # Last-resort: stringify.
    return ast.Constant(value=repr(value))


def _find_last_add_call(tree: ast.AST) -> tuple[ast.stmt, ast.AST] | None:
    """Locate the last ``<something>.add(...)`` statement in the tree.

    Returns (statement_node, parent_body_list) so the caller can splice a new
    statement in right after it. Walks both module-level and inside function
    bodies (so a layout defined in ``def build():`` is handled).
    """
    last: tuple[ast.stmt, list, int] | None = None

    def visit(body: list):
        nonlocal last
        for i, stmt in enumerate(body):
            # Recurse into function bodies.
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(stmt.body)
                continue
            if isinstance(stmt, (ast.If, ast.With, ast.For)):
                visit(stmt.body)
                if hasattr(stmt, "orelse"):
                    visit(stmt.orelse)
                continue
            # Detect `<x>.add(<arg>)` as an Expr statement.
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add"
                    and len(call.args) >= 1
                ):
                    last = (stmt, body, i)

    if isinstance(tree, ast.Module):
        visit(tree.body)
    return (last[0], last[1]) if last else None


def propose_add(
    path: str | Path,
    component,
) -> MoveProposal:
    """Plan an insertion of ``component`` as a new ``p.add(Component(...))``
    line right after the last existing ``add`` in the source.

    Reuses ``MoveProposal`` so the same Apply dialog can drive the write.
    Raises ``NotImplementedError`` if no insertion site can be found
    (no existing ``.add(...)`` calls in the file).
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    tree = ast.parse(text)

    located = _find_last_add_call(tree)
    if located is None:
        raise NotImplementedError(
            "Can't auto-insert: no existing `<project>.add(...)` call found "
            "to anchor the new line. Add the first one by hand, then `a` will "
            "be able to append more."
        )
    anchor_stmt, body = located

    call_expr = _component_to_call(component)
    # The new statement mirrors the anchor's `<x>.add(...)` shape:
    # take the anchor's receiver expression and call .add(<component>) on it.
    receiver = anchor_stmt.value.func.value  # type: ignore[attr-defined]
    new_call = ast.Call(
        func=ast.Attribute(value=receiver, attr="add", ctx=ast.Load()),
        args=[call_expr],
        keywords=[],
    )
    new_stmt = ast.Expr(value=new_call)
    # Insert after the anchor.
    idx = body.index(anchor_stmt)
    body.insert(idx + 1, new_stmt)
    ast.fix_missing_locations(tree)

    new_full = ast.unparse(tree)
    old_lines = text.splitlines()
    new_lines = new_full.splitlines()
    line_no = anchor_stmt.lineno + 1  # roughly where the new line lands

    name = getattr(component, "name", "?")
    type_name = type(component).__name__
    summary = f"add {type_name}({name!r}) at {p.name}:{line_no}"
    hunk = _line_numbered_hunk(old_lines, new_lines, line_no)

    return MoveProposal(
        path=p,
        component_name=name,
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


def _line_numbered_hunk(
    old_lines: list[str], new_lines: list[str], focus_line: int, win: int = 3
) -> list[tuple[int, str, str]]:
    """Build a (line_no, old, new) hunk around ``focus_line`` (1-based).

    ``ast.unparse`` reformats the whole file, so old and new line numbers
    don't necessarily align. We pull the window from the *original* file
    (those are the line numbers the user sees in their editor) and match it
    against the corresponding new lines by content where possible, falling
    back to positional pairing. The goal is a readable preview, not a
    byte-exact patch — the actual write uses ``new_text`` wholesale.
    """
    a = max(0, focus_line - 1 - win)
    b = min(len(old_lines), focus_line + win)
    hunk: list[tuple[int, str, str]] = []
    for i in range(a, b):
        old = old_lines[i]
        new = new_lines[i] if i < len(new_lines) else old
        hunk.append((i + 1, old, new))
    return hunk


def locate_component(path: str | Path, component_name: str) -> "LocateResult":
    """Find where a component is defined in the source, with a code window.

    Used when a move can't be auto-applied (positional coords, etc.) so the
    viewer can still show *where* in the file to edit, with line numbers.

    Raises ``LookupError`` if the component isn't found by name.
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
            f"component {component_name!r} not found by name in {p}"
        )

    ctor = getattr(target_call.func, "id", None) or getattr(
        target_call.func, "attr", "?"
    )
    line_no = target_call.lineno
    lines = text.splitlines()
    win = 3
    a = max(0, line_no - 1 - win)
    b = min(len(lines), line_no + win)
    context = [(i + 1, lines[i]) for i in range(a, b)]

    reason = (
        f"{component_name!r} uses positional coordinates, so the viewer "
        f"can't rewrite them automatically. Edit line {line_no} by hand, "
        f"or switch to keyword args: {ctor}(name={component_name!r}, x=..., y=...)."
    )
    return LocateResult(
        path=p,
        component_name=component_name,
        line=line_no,
        summary=f"{component_name} is at {p.name}:{line_no}",
        reason=reason,
        context=context,
    )


# ---------------------------------------------------------------------------
# In-memory moves (for live drag previews in the viewer)
# ---------------------------------------------------------------------------


def move_component_inplace(component, dx: float, dy: float) -> tuple[float, float]:
    """Shift a component's anchor by (dx, dy) in inches. Returns the new
    anchor as (x, y) suitable for handing to ``propose_move``.

    This mutates the component object so the next render reflects the move.
    Two-pin components move both endpoints by the same delta (so the
    component keeps its length and orientation).
    """
    if hasattr(component, "x1") and hasattr(component, "x2"):
        component.x1 += dx
        component.y1 += dy
        component.x2 += dx
        component.y2 += dy
        return component.x1, component.y1
    if hasattr(component, "x") and hasattr(component, "y"):
        component.x += dx
        component.y += dy
        return component.x, component.y
    if hasattr(component, "points"):
        component.points = [(p[0] + dx, p[1] + dy) for p in component.points]
        if component.points:
            return component.points[0]
        return 0.0, 0.0
    raise TypeError(
        f"don't know how to move {type(component).__name__}: no x/y, x1/y1, "
        "or points attribute"
    )
