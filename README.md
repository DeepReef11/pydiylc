# pydiylc

Python emitter for [DIYLC](https://github.com/bancika/diy-layout-creator) `.diy`
files. Write circuit layouts in code, open them in DIYLC.

This is an *emitter*, not a viewer or full reimplementation. DIYLC stays as the
rendering engine — pydiylc just produces files it can open.

## Status

Pre-alpha. Current component set:

- **Boards**: `BlankBoard`, `PerfBoard`, `VeroBoard` (stripboard)
- **Passives**: `Resistor`, `RadialFilmCapacitor`, `RadialCeramicDiskCapacitor`, `RadialElectrolytic`, `AxialFilmCapacitor`, `AxialElectrolyticCapacitor`, `PotentiometerPanel`
- **Semiconductors**: `DiodePlastic`, `LED`, `TransistorTO92`, `DIL_IC`
- **Connectivity**: `CopperTrace`, `Jumper`, `HookupWire`, `SolderPad`, `Dot`, `Eyelet`, `Turret`, `Line`, `TraceCut`
- **Electromechanical**: `MiniToggleSwitch` (incl. 3PDT bypass), `PlasticDCJack`, `OpenJack1_4`
- **Tubes**: `TubeSocket` (B7G / B9A / OCTAL / ...)
- **Shapes**: `Rectangle`, `Ellipse`
- **Schematic symbols**: `ResistorSymbol`, `CapacitorSymbol`, `DiodeSymbol`, `BJTSymbol`
- **Misc**: `Label`, `GroundSymbol`

**Corpus coverage:** 96.4% component recognition on the DIYLC regression corpus (52,858 of 54,841 components across 423 of 425 real community layouts).

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

Your `.py` file should expose either a top-level `project = Project(...)` or
a `def build() -> Project`. The viewer calls it on every reload.

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
