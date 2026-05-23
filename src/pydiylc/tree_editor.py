"""Tree-editor model + navigation state for the keyboard editing mode.

Steps 4-5 of the keyboard tree editor (see ``docs/keyboard-tree-editor.md``).

The *model and navigation* live here and are pure/headless — fully testable
without GTK. The actual GTK side panel and key controllers live in
``viewer.py`` and call into this.

The tree is two levels:

    component
      └─ node (control point)

Multi-node bodies (transistors, pots, ...) expose their derived pins as
read-only children: selecting one is treated as selecting the body, because
those pins aren't independently movable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import Project
from .graph import control_points_of


# Component classes whose nodes are derived (move the body, not a single pin).
def _is_multinode(component) -> bool:
    return (
        hasattr(component, "_control_points")
        and not hasattr(component, "points")
        and not (hasattr(component, "x1") and hasattr(component, "x2"))
    )


def addable_component_types() -> list[str]:
    """Names of component classes the 'add' flow can create, alphabetized."""
    from .components import ALL_COMPONENTS

    return sorted(c.__name__ for c in ALL_COMPONENTS)


# Type-aware default sizes for newly-added two-pin components, in inches.
# Boards are large enough to actually fit components on; small parts get a
# resistor-sized body; shape annotations get a roomy frame.
_DEFAULT_TWO_PIN_SIZE: dict[str, tuple[float, float]] = {
    # Boards: ~1 in × 0.7 in (10 × 7 holes at 0.1 in spacing).
    "BlankBoard": (1.0, 0.7),
    "PerfBoard": (1.0, 0.7),
    "VeroBoard": (1.0, 0.7),
    # Shape annotations: a visible frame.
    "Rectangle": (1.0, 0.5),
    "Ellipse": (1.0, 0.5),
    # Jumper / Resistor / caps / diodes / LED / symbols: small body.
    # (Anything not listed falls through to a 0.3 × 0 default.)
}


def make_default_component(type_name: str, name: str, x: float, y: float):
    """Create a component of ``type_name`` at (x, y) with sensible defaults.

    Defaults are type-aware: boards get a ~1×0.7 in rectangle so they fit
    components, shape annotations get a roomy frame, and small two-pin parts
    (resistors, caps, diodes, LED, jumpers, symbols) get a ~0.3 in body.
    Points-list components get a 1-inch segment; single-anchor / multi-node
    parts go at (x, y) and `Label`'s text defaults to its name.

    Raises ValueError for an unknown type.
    """
    import dataclasses
    from .components import ALL_COMPONENTS

    by_name = {c.__name__: c for c in ALL_COMPONENTS}
    cls = by_name.get(type_name)
    if cls is None:
        raise ValueError(f"unknown component type: {type_name!r}")

    fields = {f.name for f in dataclasses.fields(cls)}
    kwargs: dict = {"name": name}
    if "x1" in fields and "x2" in fields:
        dx, dy = _DEFAULT_TWO_PIN_SIZE.get(type_name, (0.3, 0.0))
        kwargs.update(
            x1=x, y1=y,
            x2=round(x + dx, 4), y2=round(y + dy, 4),
        )
    elif "points" in fields:
        kwargs["points"] = [(x, y), (round(x + 1.0, 4), y)]
    elif "x" in fields and "y" in fields:
        kwargs.update(x=x, y=y)
    if "text" in fields:
        kwargs["text"] = name
    return cls(**kwargs)


@dataclass
class TreeNode:
    """One row in the tree: either a component header or a node child."""

    component_index: int
    point_index: int | None  # None = the component header row
    label: str
    is_node: bool
    movable: bool  # False for derived multi-node pins
    x: float | None = None
    y: float | None = None


def build_tree(project: Project) -> list[TreeNode]:
    """Flatten a project into an ordered list of tree rows.

    Each component yields a header row, followed by its node rows (if it has
    individually addressable nodes). Two-pin → 2 nodes; points-list → N;
    single-anchor → the header is the node; multi-node → header + read-only
    pin rows.
    """
    rows: list[TreeNode] = []
    for i, comp in enumerate(project.components):
        name = getattr(comp, "name", f"#{i}")
        type_name = type(comp).__name__
        rows.append(
            TreeNode(i, None, f"{name}  ({type_name})", is_node=False, movable=True)
        )
        pts = control_points_of(comp, i)
        if _is_multinode(comp):
            # Read-only pin children.
            for cp in pts:
                rows.append(
                    TreeNode(
                        i, cp.point_index, f"pin {cp.point_index + 1}  "
                        f"({cp.x:g}, {cp.y:g})", is_node=True, movable=False,
                        x=cp.x, y=cp.y,
                    )
                )
        elif hasattr(comp, "x1") and hasattr(comp, "x2"):
            labels = ["end 1", "end 2"]
            for cp in pts:
                rows.append(
                    TreeNode(
                        i, cp.point_index,
                        f"{labels[cp.point_index]}  ({cp.x:g}, {cp.y:g})",
                        is_node=True, movable=True, x=cp.x, y=cp.y,
                    )
                )
        elif hasattr(comp, "points"):
            for cp in pts:
                rows.append(
                    TreeNode(
                        i, cp.point_index,
                        f"point {cp.point_index + 1}  ({cp.x:g}, {cp.y:g})",
                        is_node=True, movable=True, x=cp.x, y=cp.y,
                    )
                )
        # single-anchor: the header row *is* the node; no children.
    return rows


@dataclass
class NavState:
    """Keyboard navigation cursor over the tree.

    Tracks which row is focused and which component "owns" the current Tab
    walk (so Tab through a component's nodes stays within that component even
    when a node is a shared junction — per the design's shared-node rule).
    """

    rows: list[TreeNode]
    cursor: int = 0  # index into rows
    tab_owner: int | None = None  # component_index that Tab is walking
    node_level: bool = False  # True when drilled into a component's nodes

    # -- selection ---------------------------------------------------------

    @property
    def current(self) -> TreeNode | None:
        if 0 <= self.cursor < len(self.rows):
            return self.rows[self.cursor]
        return None

    # -- component-list navigation (up/down move between component headers) -

    def _header_indices(self) -> list[int]:
        return [i for i, r in enumerate(self.rows) if not r.is_node]

    def next_component(self) -> None:
        self.node_level = False
        headers = self._header_indices()
        if not headers:
            return
        cur_comp = self.current.component_index if self.current else -1
        # Find the next header strictly after the current component.
        for hi in headers:
            if self.rows[hi].component_index > cur_comp:
                self.cursor = hi
                self.tab_owner = self.rows[hi].component_index
                return
        # Wrap to first.
        self.cursor = headers[0]
        self.tab_owner = self.rows[headers[0]].component_index

    def prev_component(self) -> None:
        self.node_level = False
        headers = self._header_indices()
        if not headers:
            return
        cur_comp = self.current.component_index if self.current else 10**9
        for hi in reversed(headers):
            if self.rows[hi].component_index < cur_comp:
                self.cursor = hi
                self.tab_owner = self.rows[hi].component_index
                return
        self.cursor = headers[-1]
        self.tab_owner = self.rows[headers[-1]].component_index

    # -- node walking within the focused component (Tab / Shift-Tab) --------

    def _node_rows_for(self, component_index: int) -> list[int]:
        return [
            i for i, r in enumerate(self.rows)
            if r.component_index == component_index and r.is_node
        ]

    def first_node(self) -> None:
        """Enter the focused component's nodes (→ / Enter)."""
        if self.current is None:
            return
        ci = self.current.component_index
        self.tab_owner = ci
        nodes = self._node_rows_for(ci)
        if nodes:
            self.cursor = nodes[0]

    def to_header(self) -> None:
        """Collapse back to the component header (←)."""
        if self.current is None:
            return
        ci = self.current.component_index
        for i, r in enumerate(self.rows):
            if r.component_index == ci and not r.is_node:
                self.cursor = i
                return

    def has_nodes(self) -> bool:
        """True if the focused component has individually addressable nodes."""
        if self.current is None:
            return False
        return bool(self._node_rows_for(self.current.component_index))

    def enter_nodes(self) -> bool:
        """Drill into the focused component's nodes. Returns False (no-op) if
        the component has no addressable nodes (single-anchor / multi-node)."""
        if not self.has_nodes():
            return False
        self.first_node()
        self.node_level = True
        return True

    def exit_nodes(self) -> None:
        """Pop back to component-header level."""
        self.to_header()
        self.node_level = False

    def next_node(self) -> None:
        """Tab: next node within the tab_owner component."""
        owner = self.tab_owner
        if owner is None and self.current is not None:
            owner = self.current.component_index
            self.tab_owner = owner
        nodes = self._node_rows_for(owner)
        if not nodes:
            return
        if self.cursor in nodes:
            pos = nodes.index(self.cursor)
            self.cursor = nodes[(pos + 1) % len(nodes)]
        else:
            self.cursor = nodes[0]

    def prev_node(self) -> None:
        owner = self.tab_owner
        if owner is None and self.current is not None:
            owner = self.current.component_index
            self.tab_owner = owner
        nodes = self._node_rows_for(owner)
        if not nodes:
            return
        if self.cursor in nodes:
            pos = nodes.index(self.cursor)
            self.cursor = nodes[(pos - 1) % len(nodes)]
        else:
            self.cursor = nodes[-1]

    def focus_node(self, component_index: int, point_index: int | None) -> bool:
        """Move the cursor to a specific component/node (used by / search).

        If point_index is None, focuses the component header. Returns True if
        a matching row was found.
        """
        for i, r in enumerate(self.rows):
            if r.component_index == component_index and r.point_index == point_index:
                self.cursor = i
                self.tab_owner = component_index
                self.node_level = r.is_node
                return True
        # Fall back: focus the component header.
        for i, r in enumerate(self.rows):
            if r.component_index == component_index and not r.is_node:
                self.cursor = i
                self.tab_owner = component_index
                self.node_level = False
                return True
        return False

    def clamp_cursor(self) -> None:
        """Keep the cursor in range after rows shrink."""
        if not self.rows:
            self.cursor = 0
            self.node_level = False
            return
        self.cursor = max(0, min(self.cursor, len(self.rows) - 1))

    def rebuild(self, project: Project) -> None:
        """Refresh rows after an edit, keeping the cursor on the same
        component/point where possible."""
        prev = self.current
        self.rows = build_tree(project)
        if prev is None:
            self.cursor = 0
            return
        for i, r in enumerate(self.rows):
            if (
                r.component_index == prev.component_index
                and r.point_index == prev.point_index
            ):
                self.cursor = i
                return
        self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
