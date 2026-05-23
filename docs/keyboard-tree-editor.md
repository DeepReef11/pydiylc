# Design: keyboard tree editor

Status: **draft / not yet implemented.** This documents the target design for
a keyboard-driven, tree-based editing mode in the viewer, per the feature
request. No code exists for it yet beyond the existing drag-to-move and
`pydiylc.edit` AST surgery.

## Goal

Make the viewer fully keyboard-controllable for moving and rotating
components and their individual nodes, with a side panel that lists
components and lets you drill into each component's nodes. Movement is
*connection-aware*: a node can jump to legal destinations (other nodes,
perfboard holes), and literal nudges respect how things are attached
(a part mounted on a board moves the board; a part wired to others stretches
the wires).

## The 4 coordinate models (what a "node" is)

pydiylc components store geometry in one of four ways. The tree editor must
treat each correctly:

| Model | Components | Nodes |
|---|---|---|
| **two-pin** (`x1,y1,x2,y2`) | Resistor, caps, diodes, Jumper, **boards** (corners), Rectangle, Ellipse | 2 movable endpoints |
| **points-list** (`points=[...]`) | CopperTrace, CurvedTrace, HookupWire, Line | N movable points |
| **multi-node** (auto `_control_points()`) | pots, trimmers, TubeSocket, TransistorTO92, BJTSymbol, MiniToggleSwitch, TerminalStrip | derived from a single anchor — move the *anchor*, pins follow; individual pins are NOT independently movable |
| **single-anchor** (`x,y`) | DIL_IC, SolderPad, Dot, Eyelet, Turret, TraceCut, jacks, Label, Image, BOM, GroundSymbol | 1 anchor |

Implication: the tree expands differently per model. Two-pin shows
`[component] → end 1, end 2`. Points-list shows `[component] → point 1..N`.
Multi-node shows `[component]` with read-only pin children (informational;
moving them moves the whole part). Single-anchor shows just `[component]`.

## Connectivity graph (the hard part)

Two control points at the *same coordinate* form a **junction**. The editor
builds a graph where:

- **Nodes** = unique (x, y) coordinates that ≥1 component touches.
- **Edges** = "component C touches junction J at control-point index i".

Edge **type** is inferred from the component:

- **mount**: the component sits *on* a board — its anchor/points fall inside a
  board's rectangle. Moving the board moves all mounted components rigidly.
  (Detected geometrically: is the point inside a `*Board` rect?)
- **lead/wire**: the component is a `HookupWire`, `CopperTrace`, `CurvedTrace`,
  `Jumper`, or `Line`. Moving one endpoint stretches it; the other endpoint
  and whatever it connects to stay put.
- **rigid-pin**: a component's own multiple control points (e.g. a transistor's
  3 legs) move together as one body.

### Move propagation rules

When the user moves node/component X by Δ:

1. **Board move** → translate the board rect + every component whose anchor is
   inside it, by Δ. Wires crossing the board boundary stretch (only their
   inside endpoints move).
2. **Mounted component move** → translate just that component by Δ. Any wire
   endpoint coincident with one of its (moved) pins moves too (stays
   connected); the wire's far end stays. This is the "leads stretch" behavior.
3. **Free wire endpoint move** → move only that endpoint.

Open question: should coincidence be re-evaluated continuously during a move
(so you can *detach* by dragging away) or only at attach time? Proposed: a node
stays attached while you move the owning component, but a *node-level* move
(Tab into a wire endpoint, then nudge) detaches it. Mirrors how DIYLC behaves.

## Two move modes

### Jump-to-target (default — arrow keys)

Inspired by vim-flash / easymotion. Press an arrow with a node focused:

1. Compute legal destinations: all other junctions + (if over a perfboard) the
   board's hole grid positions, filtered to the half-plane in the arrow's
   direction.
2. Label each candidate with a key hint overlay.
3. User presses the hint key → node snaps there (creating/joining a junction).

This makes "connect R1's free leg to the transistor base" a 3-keystroke op
instead of pixel-perfect dragging.

### Literal nudge (Ctrl+arrow coarse, Ctrl+Shift+arrow fine)

Metric movement honoring attachment rules above.

- Ctrl+arrow = 1 grid step (project `grid_inches`, default 0.1 in).
- Ctrl+Shift+arrow = 1/10 grid step (fine).

(Originally considered px-based; grid-based is better since DIYLC layouts are
grid-native.)

## Rotation (later primitive)

For multi-node and two-pin components: rotate control points about the
component's anchor/centroid by 90° (R key) or free angle (with modifier).
Two-pin → swap/rotate endpoints; multi-node → most already have an
`orientation` enum, so rotation = cycle that enum and re-derive pins, which is
cleaner than rotating raw coordinates. Single-anchor with an `orientation`
field (DIL_IC, jacks) likewise cycles the enum.

## Side panel + keyboard map

```
┌── Components ────────────┐
│ ▸ Board1   (VeroBoard)   │   ← collapsed
│ ▾ R1       (Resistor)    │   ← expanded
│     • end 1  (1.5, 1.4)  │
│     • end 2  (1.5, 1.6)  │
│ ▸ Q1       (TransistorTO92)
│ ▸ W_in     (HookupWire)  │
└──────────────────────────┘
```

| Key | Action |
|---|---|
| ↑/↓ (in list) | move selection between components |
| → / Enter | expand component / focus first node |
| ← | collapse / back to component |
| Tab / Shift-Tab | next/prev node *within* the focused component |
| arrows (canvas focus) | jump-to-target move of focused node |
| Ctrl+arrows | literal coarse nudge |
| Ctrl+Shift+arrows | literal fine nudge |
| R / Shift+R | rotate 90° CW / CCW |
| n / p | jump to next/prev component touching the focused junction |
| Enter (after move) | commit → propose source edit (existing dialog) |
| Esc | cancel current move |

### Shared-node Tab behavior (from the request)

When Tab lands on a node that is shared with another component, the *other*
component becomes the move target for that node, but the tree focus stays in
the original component — so the next Tab continues through the original
component's remaining nodes, not the neighbor's. This keeps "walk this
component's pins" intuitive even when pins are shared junctions.

## Source round-trip

Every committed move/rotate routes through the existing
`pydiylc.edit.propose_move` → diff dialog → `apply_proposal` path, extended to:

- per-node edits (currently only anchor / first-endpoint and `second_point`
  are supported; need x2/y2 + arbitrary `points[i]` rewrites),
- enum edits for orientation-based rotation.

Components built with positional coords still fall back to the read-only
`locate_component` dialog.

## Incremental build plan

1. **Connectivity graph module** (`pydiylc.graph`): build junctions + typed
   edges from a Project; classify mount/wire/rigid. Pure, fully unit-testable
   headless. *(Start here — it's the foundation and needs no GTK.)*
2. **Move engine** (`pydiylc.moves`): given (target, Δ, mode), compute the new
   coordinate set per the propagation rules. Pure + testable.
3. **Per-node AST edits**: extend `edit.py` to rewrite `x2/y2` and
   `points[i]`, plus orientation enums.
4. **Side panel widget** + tree model in the viewer (GTK).
5. **Keyboard controllers**: list nav, Tab, nudge, jump-to-target overlay.
6. **Rotation.**

Steps 1–3 are headless and land first with full test coverage. Steps 4–6 need
a GTK host to iterate on (the sandbox can't run them), so they'll be built
against the tested core and verified on real hardware.

## Implementation status

- **Step 1 — connectivity graph** (`pydiylc.graph`): done, tested.
- **Step 2 — move engine** (`pydiylc.moves`): done, tested. `move_component`,
  `move_node`, `move_node_to`.
- **Step 3 — per-node AST edits** (`pydiylc.edit.propose_point_move`): done,
  tested.
- **Step 6 — rotation** (`pydiylc.moves.rotate_component`): done, tested.
  Enum-cycle for oriented components, coordinate rotation otherwise.
- **Steps 4–5 — tree model + nav + GTK panel/keys**: model and navigation
  (`pydiylc.tree_editor`) done and tested headless. The GTK side panel and
  key controllers (in `viewer.py`) are written but **not yet verified on
  hardware** — the sandbox has no display. Toggle with `T`.

### Implemented keybindings (tree mode, press `T` to enter)

| Key | Action |
|---|---|
| T | toggle tree-editor panel |
| Tab / Shift-Tab | at component level: next / prev component; at node level: next / prev node within the focused component |
| Space | drill into the focused component's nodes / pop back out |
| Ctrl+arrows | nudge focused component/node by one grid step |
| Ctrl+Shift+arrows | nudge by 1/10 grid step (fine) |
| R / Shift+R | rotate 90° CW / CCW |
| Enter | commit the focused component's position to source (diff dialog) |
| Esc / Q | exit tree mode |

Additional bindings:

| Key | Action |
|---|---|
| arrows (plain) | move the focused node by one board hole (grid step off-board) |
| / | fuzzy-search to **focus** any node (searchable Tab nav) |
| g | fuzzy-search to **send** the focused node onto another node's position |
| a | add a new component (fuzzy type picker), placed near the focused one |
| dd | delete the focused component (press `d` twice; any other key cancels) |
| u | undo the last edit (move / rotate / add / delete) |

Undo is a snapshot stack (`pydiylc.history.History`): every mutating action
deep-copies the component list first; `u` restores the previous snapshot.
Bounded to 100 entries. In-memory only — undo doesn't touch the source file
(commit edits to source explicitly with Enter).

The `/` and `g` menus share `jump.searchable_targets` + `jump.fuzzy_filter`
(subsequence match, spaces ignored, contiguous matches ranked first). `/`
moves the cursor; `g` snaps the focused node to the chosen target. Both are
"like Tab navigation but fuzzy".

`a` creates the component in-memory via `tree_editor.make_default_component`
(two-pin → short body, points-list → 1-inch segment, single-anchor → at the
point). It does **not** yet write the new component back to the `.py` source —
that needs AST insertion, a future step.

**GTK note:** the key controller is attached in the **CAPTURE** propagation
phase. Without this, GTK consumes Tab/Shift-Tab for default focus traversal
(and the focused ListBox eats arrow keys) before they reach the handler.
Capture phase intercepts keys at the window level first.

### Not yet built

- Jump-to-target move mode (vim-flash-style destination overlay on plain
  arrows). Currently plain arrows navigate the tree; literal nudge is
  Ctrl+arrows. The jump overlay needs canvas-space candidate rendering.
- Shared-node "n / p jump to neighbor component" keys.
- **Working-buffer save flow:** implemented in `pydiylc.buffer.Buffer` +
  `pydiylc.prefs.Prefs`. The viewer holds a `Buffer` per tree-mode session
  (loaded from disk on entry); every edit mutates the buffer immediately
  via `Buffer.propose()` + `apply()` against itself (not disk). `Enter` or
  `Ctrl+S` invokes `_save_buffer()` which opens a diff-on-save dialog with
  a "Don't show again" checkbox (toggles `prefs.show_save_dialog`,
  persisted to `~/.config/pydiylc/prefs.json`); subsequent saves are
  silent. The status bar shows ● unsaved while the buffer is dirty.

  Caveats today: rotate and delete update the in-memory project but don't
  yet write back to the buffer (no orientation-keyword or line-removal
  surgery), so they're flagged in the status bar with a "won't be saved"
  hint. Move + add are fully buffer-synced.

- **Auto-wire-on-add (parked):** when adding a component with a node
  focused (e.g. VR1 pin 1), automatically create a wire/connection
  linking the new component to the focused pin. For multi-pin added
  components, fuzzy-select which of its pins to attach to. Uppercase
  `A` would add without auto-attaching.

- **Page-Up/Page-Down navigation (parked):** scroll a page at a time
  in fuzzy menus and in the side tree panel. Simple addition to
  `_move_list_selection` (jump by page-size rows) and the tree-mode key
  handler.
```
