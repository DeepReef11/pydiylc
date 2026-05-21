# Changelog

## v0.2.0 — 2026-05-21

### Viewer: drag-to-move with diff preview (stage 3)

Ctrl+drag a component in the GTK4 viewer to move it. On release, the move is
snapped to the project grid and:

- If the layout is a `.py` file with keyword-arg components, the viewer
  computes an AST-surgery source rewrite and shows a diff dialog with an
  **Apply** button. Applying writes the file; the watcher reloads.
- Otherwise the move stays in-memory and the new coordinates are reported.

New `pydiylc.edit.move_component_inplace()` shifts a component (single-anchor,
two-pin, or points-list) by a delta for live drag previews.

### New components (40 total, was 36)

- `TrimmerPotentiometer` (diylc.passive.TrimmerPotentiometer)
- `TerminalStrip` (diylc.boards.TerminalStrip)
- `Image` (diylc.misc.Image) — base64 blob passthrough
- `BOM` (diylc.misc.BOM) — bill-of-materials placeholder

Plus reader aliases for `OpenJack1__4` (double-underscore legacy spelling).

### Corpus recognition: 96.4% → 97.5%

53,366 of 54,727 components across 423 of 425 community files. Remaining
unknowns are GroundFill, chassis cutouts, PinHeader, Polygon — none core to
layout work.

### PNG export

`pydiylc render layout.diy --out preview.png` rasterizes via pycairo
(`pydiylc.cairo_render.render_png`). Falls back with a clear error when
pycairo isn't installed.

### Packaging

- Builds clean wheel + sdist (`python -m build`), passes `twine check`.
- `catalog.json` and `LLMS.txt` are bundled in the wheel under
  `pydiylc/data/`; `bundled_catalog_path()` / `bundled_llms_txt_path()`
  locate them at runtime.
- Full PyPI classifiers, project URLs, `PUBLISHING.md` release runbook.
- Version bumped to 0.2.0.

### Tests

165 passing, 2 skipped (PNG tests need a working pycairo). New: stage-3
move helper, PNG export + graceful fallback, new-component round-trips.

## v0.1.0 — 2026-05-21

First tagged release. Pydiylc reaches a usable v1: it emits and reads DIYLC
`.diy` files, renders previews, and ships a Wayland-native GTK4 viewer.

### Components (36 total)

- **Boards**: BlankBoard, PerfBoard, VeroBoard
- **Passives**: Resistor, RadialFilmCapacitor, RadialCeramicDiskCapacitor,
  RadialElectrolytic, AxialFilmCapacitor, AxialElectrolyticCapacitor,
  PotentiometerPanel, ResistorSymbol, CapacitorSymbol
- **Semiconductors**: DiodePlastic, LED, TransistorTO92, DIL_IC, DiodeSymbol,
  BJTSymbol
- **Connectivity**: CopperTrace, CurvedTrace, Jumper, HookupWire, SolderPad,
  Dot, Eyelet, Turret, Line, TraceCut
- **Electromechanical**: MiniToggleSwitch (incl. 3PDT bypass),
  PlasticDCJack, OpenJack1_4
- **Tubes**: TubeSocket (B7G / B9A / OCTAL / ...)
- **Shapes**: Rectangle, Ellipse
- **Misc**: Label, GroundSymbol

### Round-trip & corpus coverage

- Emits modern DIYLC 5.x `.diy` XML; output opens in DIYLC unchanged.
- Reads back into Project, accepts both modern `<project>` and v3
  `<org.diylc.core.Project>` roots, and both `diylc.*` and
  `org.diylc.components.*` class-name prefixes.
- Tested against the 425-file DIYLC regression corpus:
  - **99.5% of v3+ files parse**
  - **96.4% of components recognized**
  - Unknown components produce warnings, not failures

### Output formats

- `.diy` (DIYLC native)
- `.json` (LLM-friendly serialization)
- `.svg` (browser preview)
- Live GTK4 viewer (Wayland-native, no XWayland, no Java)

### CLI

- `pydiylc convert IN OUT` — `.py` / `.json` / `.diy` → `.diy` / `.json` / `.svg`
- `pydiylc render FILE [--out OUT] [--dpi N]`
- `pydiylc info FILE`
- `pydiylc-view FILE` — GTK4 viewer with file-watcher reload, pan/zoom/click-select

### AI-friendly surface

- `LLMS.txt` (llmstxt.org-style flat doc)
- `catalog.json` (machine-readable schema of every component, field, enum)
- `Project.from_dict(...)` accepts a plain dict for LLM-driven layout
- Strict enum validation with allowed-value-listing errors
- Per-component docstrings list the exact `.diy` element they emit

### MCP server

`pydiylc-mcp` exposes pydiylc as an MCP tool surface for LLM clients
(Claude Desktop, Claude Code, mcp-cli, etc.). Tools:

- `list_component_types` — full catalog
- `create_project` / `create_project_from_dict`
- `add_component` / `list_components` / `remove_component`
- `save` / `render_svg` / `to_json` / `read_diy`

In-memory store keyed by `project_id` supports multiple parallel layouts.

### AST-surgery edit module (`pydiylc.edit`)

Foundation for "drag a component in the viewer, see what would change in
the Python source, click Apply." `propose_move(path, name, x, y)` returns a
``MoveProposal`` with old/new source text and a diff hunk; nothing is
written until `apply_proposal(proposal)` is called.

This is intentionally narrow in v0.1: only single-anchor and two-pin
coordinate edits, only on components built with keyword args. Stage 3
viewer integration (drag → propose → preview → apply) is the next round.

### Test suite

159 tests covering: emission shape, JSON loader, .diy reader, every
component's enum validation, SVG renderer dispatch, Cairo backend dispatch,
viewer loaders without GTK, CLI subcommands, MCP tool registration, AST
edit roundtrip.
