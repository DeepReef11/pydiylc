# pydiylc

![tests](https://img.shields.io/badge/tests-165%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![corpus](https://img.shields.io/badge/corpus%20recognition-97.5%25-brightgreen)

A scriptable Python library — and a native Wayland GTK4 viewer — for
[DIYLC](https://github.com/bancika/diy-layout-creator) circuit layouts.

- **Write layouts in Python or JSON**, save them as `.diy` (opens in DIYLC).
- **Read existing `.diy` files** back into Python (97.5% component recognition
  on the DIYLC community corpus).
- **Preview natively** — SVG for browsers, PNG via cairo, or a Wayland-native
  GTK4 viewer with pan/zoom/click-select and drag-to-move-with-diff.
- **CLI** (`pydiylc convert/render/info`) and an **MCP server** for LLM clients.

DIYLC itself remains the canonical renderer; pydiylc produces and consumes the
same `.diy` format and adds a scriptable, Java-free, Wayland-friendly workflow
on top.

> **New here?** [**`docs/GETTING_STARTED.md`**](docs/GETTING_STARTED.md) is a
> 15-minute beginner walkthrough — assumes no Python virtual-environment
> experience and gets you from `git clone` to an open editor window.

## Status

Beta (v0.2.0). Current component set (40 types):

- **Boards**: `BlankBoard`, `PerfBoard`, `VeroBoard` (stripboard)
- **Passives**: `Resistor`, `RadialFilmCapacitor`, `RadialCeramicDiskCapacitor`, `RadialElectrolytic`, `AxialFilmCapacitor`, `AxialElectrolyticCapacitor`, `PotentiometerPanel`, `TrimmerPotentiometer`
- **Semiconductors**: `DiodePlastic`, `LED`, `TransistorTO92`, `DIL_IC`
- **Connectivity**: `CopperTrace`, `Jumper`, `HookupWire`, `SolderPad`, `Dot`, `Eyelet`, `Turret`, `Line`, `TraceCut`
- **Electromechanical**: `MiniToggleSwitch` (incl. 3PDT bypass), `PlasticDCJack`, `OpenJack1_4`
- **Tubes**: `TubeSocket` (B7G / B9A / OCTAL / ...)
- **Shapes**: `Rectangle`, `Ellipse`
- **Boards**: `BlankBoard`, `PerfBoard`, `VeroBoard`, `TerminalStrip`
- **Schematic symbols**: `ResistorSymbol`, `CapacitorSymbol`, `DiodeSymbol`, `BJTSymbol`
- **Misc**: `Label`, `GroundSymbol`, `Image`, `BOM`

**Corpus coverage:** 97.5% component recognition on the DIYLC regression corpus (53,366 of 54,727 components across 423 of 425 real community layouts).

## CLI

```bash
pydiylc convert layout.py layout.diy          # build from Python
pydiylc convert layout.diy layout.json        # extract to JSON
pydiylc render  layout.diy --out preview.svg  # SVG preview
pydiylc info    layout.diy                    # summary + warnings
```

`pydiylc convert` accepts `.py`, `.json`, or `.diy` in and writes `.diy`,
`.json`, or `.svg` out. Full `py → diy → json → diy` round-trip is exercised
in the test suite. The Python loader recognizes `project = Project(...)`,
`def build()`, `def main()`, or any top-level Project assignment.

A complete pedal layout — stripboard, transistor, pot, 3PDT bypass, DC and 1/4" jacks — is buildable in code or via JSON (see `examples/demo_lpb1_stripboard.py`).

`.diy` files can also be read back into a Project:

```python
p = Project.read("downloaded_pedal.diy")
```

Tolerates modern (4.x) and v3 (XStream-prefixed) roots. Unknown component types are dropped with a warning instead of failing the parse.

## Native SVG preview

`pydiylc.svg.render_svg(project)` produces a quick-preview SVG of the layout. Component shape, position, and color are right; it is not pixel-identical to DIYLC's renderer. Good for iterating in a browser without launching DIYLC.

```python
from pydiylc.svg import render_svg_file
render_svg_file(p, "preview.svg")  # open in any browser
```

See `examples/demo_render_svg.py` for a complete LPB-1 → SVG example.

## GTK4 viewer (Wayland-native)

A native viewer ships with the package. It draws via Cairo (no Java, no Swing,
no XWayland), reloads when your source file changes, and supports pan/zoom +
click-to-select.

```bash
pip install -e ".[viewer]"        # installs PyGObject + pycairo
# you also need GTK 4 from the system: e.g. `sudo apt install gir1.2-gtk-4.0`

pydiylc-view examples/layout_for_viewer.py
pydiylc-view examples/layout.json
```

Keyboard:
- **R** — manual reload
- **0** — reset zoom + pan
- **+/-** — zoom in/out
- **Q / Esc** — quit
- **mouse drag** — pan
- **scroll** — zoom
- **click** — select component (name shown in header bar)
- **Right-click** — context menu: Add component here / Edit value / Duplicate / Rotate / Delete / Send to / Focus. The "Add here" option places the new component at the cursor (snapped to the project grid).
- **Ctrl + drag** — move a component; on release the viewer proposes the
  source edit (snapped to the grid) and shows a diff with an **Apply** button.
  Auto-apply works when the layout is a `.py` file whose components are built
  with keyword args (e.g. `Resistor(name="R1", x1=1.0, ...)`); otherwise the
  move stays in-memory and the new coordinates are shown for manual editing.

Your `.py` file should expose either a top-level `project = Project(...)` or
a `def build() -> Project`. The viewer calls it on every reload.

### Edit mode (press `T` — vim-like "insert mode")

Outside edit mode the viewer is read-only (mouse pan/zoom/click). Press `T`
to open the component side panel and enable the full keyboard editing
surface. The status bar shows ✎ EDIT while you're in.

- **Tab / Shift-Tab** — next / previous component; once you drill in, walks
  the focused component's nodes
- **Space** — drill into the focused component's nodes / pop back out
- **PgUp / PgDn** — page 10 components at a time
- **arrows** — move the focused node by one board hole (grid step off-board)
- **Ctrl+arrows** — nudge by one grid step; **Ctrl+Shift+arrows** — fine (1/10)
- **/** — fuzzy-search to focus any node (searchable navigation)
- **g** — fuzzy-search to send the focused node onto another node
- **a** — add a component (auto-wires to focused pin); **A** — add without wiring
- **v** — edit the focused component's primary value (value/text/resistance/tube_type)
- **D** — duplicate the focused component (offset 0.3in right, incremented name)
- **dd** — delete the focused component (press `d` twice)
- **u** / **Ctrl+Z** — undo the last edit
- **U** / **Ctrl+Y** — redo the last undone edit
- **R / Shift+R** — rotate 90° CW / CCW (cycles `orientation` for oriented
  parts, rotates coordinates otherwise)
- **Enter** — save the working buffer to disk (silent)
- **Ctrl+S** — save with the diff-on-save dialog (gated by a "don't show
  again" preference, persisted in `~/.config/pydiylc/prefs.json`)
- **Esc / Q** — exit edit mode

Moves are connection-aware: moving a board drags the components mounted on it,
and moving a part stretches any wires attached to it (the wire's far end stays
put). A node-level move (Tab into a node, then Ctrl+arrow) detaches that point
from its junction. See `docs/keyboard-tree-editor.md` for the full design.

> **Note:** the tree-editor GTK UI is built against a fully unit-tested core
> (graph, move engine, rotation, navigation — 60+ tests) but the GTK panel and
> key wiring themselves haven't yet been run on real hardware. Report issues.

## MCP server

For LLM clients (Claude Desktop, Claude Code, mcp-cli, etc.):

```bash
pip install -e ".[mcp]"
pydiylc-mcp                  # stdio transport
```

Exposes `list_component_types`, `create_project`, `add_component`, `save`,
`render_svg`, `read_diy`, and friends. Project state lives in-process keyed
by a `project_id` argument so a client can manage multiple parallel layouts.

## AI-friendly by design

- [`LLMS.txt`](./LLMS.txt) — one-screen overview meant to be fed to a coding
  assistant. Lists every component, the values its enum fields accept, and the
  value-string parsing rules.
- [`catalog.json`](./catalog.json) — machine-readable schema of every
  component, regenerated with `python -m pydiylc.catalog`. Fields, types,
  defaults, enum choices, and Measure units. Use this for codegen,
  prompt-stuffing, or downstream validation.
- Every component validates its enum fields at construction with a clear
  `ValueError` listing the allowed values.

## Install

```bash
pip install -e .
```

## Use

```python
from pydiylc import Project, PerfBoard, Resistor, SolderPad, CopperTrace

p = Project(title="Booster", width_cm=10, height_cm=8)
p.add(PerfBoard("Board1", x1=1.0, y1=1.0, x2=3.0, y2=2.5))
p.add(Resistor("R1", x1=1.2, y1=1.2, x2=1.2, y2=1.8, value="10K"))
p.add(SolderPad("P1", x=1.2, y=1.2))
p.add(SolderPad("P2", x=1.2, y=1.8))
p.add(CopperTrace("T1", points=[(1.2, 1.8), (2.0, 1.8)]))
p.save("booster.diy")
```

Or from JSON (the preferred path for LLMs / external tools):

```python
from pydiylc import Project

Project.from_dict({
    "title": "Booster",
    "components": [
        {"type": "PerfBoard", "name": "Board1", "x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 2.5},
        {"type": "Resistor", "name": "R1", "x1": 1.2, "y1": 1.2, "x2": 1.2, "y2": 1.8, "value": "10K"},
    ],
}).save("booster.diy")
```

Open `booster.diy` in DIYLC.

## File format

DIYLC ships file format v4.x. v5.x of the application reuses the same on-disk
schema with additive components. pydiylc targets that schema and currently
writes `<fileVersion>5.7.0</fileVersion>` so recent DIYLC builds open without a
"created with older version" warning.

Coordinates are in inches by default (DIYLC's grid is `0.1 in`).

## License

GPL-3.0-or-later, matching upstream DIYLC.
