# Changelog

## Unreleased — 2026-07-14

Bug-fix sweep across every module (44 fixes), with regression tests for each
(suite: 496 → 1110 tests) and a first live-GTK smoke run of the viewer under
Xvfb.

### Geometry & file format

- **TubeSocket wrote a DIYLC-incompatible control-point list.** Upstream
  stores the socket *center* as `controlPoints[0]` with the pin ring after
  it; pydiylc wrote the ring only, so DIYLC placed the socket off by the
  ring radius and pydiylc's own read → save → read cycle walked the anchor
  (+0.135, −0.37) per round trip. The writer now emits center-first; the
  reader accepts both layouts (legacy ring-only files recover the center
  from the ring centroid). `angle` now rotates the pin ring (upstream
  behavior) and `pin_circle_diameter` round-trips.
- **`orientation` was ignored by 29 multi-pin components** (jacks, TO-1/126/
  220, SIL_IC, lever/rotary/LP switches, relays, pickups, symbols, …): the
  enum was written to the file — so DIYLC showed the part rotated — while
  pydiylc's pins, renderers, graph, and wire-following all used the
  unrotated layout. Pins now rotate about the anchor (`Component._oriented`,
  same convention as the hand-rolled TO92 math) and both renderers wrap
  those components in the matching whole-body rotation.
- Rotating a multi-node body without an orientation/angle field (ICSymbol,
  PlasticDCJack) *translated* it to a garbage position; it is now a clean
  no-op surfaced as `RotateResult(kind="unsupported")` / an MCP warning,
  and `moves.can_rotate()` reports rotatability.
- Rotation left two-pin wires (Jumper) behind while carrying points-list
  wires; the follow logic now uses the shared control-point model.
- Field-level round-trip losses fixed: WrapLabel text, Breadboard size,
  TerminalStrip body_color, AxialElectrolyticCapacitor invert, IECSocket
  value, TransistorTO126 lead_color, `Project.dot_spacing`. A new
  parametrized sweep (`tests/test_field_round_trip.py`, 572 cases) locks
  every tweakable field of every component through save → read.
- v3 XStream nested `<value><value>10.0</value><unit>K</unit></value>`
  measures were swallowed as whitespace (values silently destroyed on
  read); 2-point CopperTrace/Line kept DIYLC's label midpoint as a path
  vertex (trace doubled back on itself when re-rendered).

### Renderers (SVG + Cairo)

- 3/5/7-point HookupWire/CurvedTrace (all legal `WIRE_POINT_COUNT`s)
  crashed the 4-point unpack and rendered as nothing; both renderers now
  draw piecewise curves through any legal count.
- Alpha was normalized as `/255`, but DIYLC's scale tops out at 127 —
  everything semi-transparent rendered at half its intended opacity.
- Cairo drew inductor/transformer-coil bumps at fixed world angles
  (sideways scallops + stray chords on vertical parts); bumps now follow
  the wire direction like the SVG side.
- Swapped-corner EyeletBoard/MarshallPerfBoard/TriPadBoard emitted
  negative-size rects (dropped as invalid by SVG viewers).
- `#`-prefixed colors produced invalid `##rrggbb` in ~60 SVG sites (now
  routed through `_color()`); Cairo now honors `Rectangle.edge_radius`;
  the SVG 2-point CurvedTrace now honors `size`.

### Viewer

- Right-click → Delete/Rotate/Edit/Duplicate (and click-then-T) acted on
  component #0 instead of the clicked part — entering tree mode now focuses
  the selection.
- Reload left the tree cursor indexing the old component list (IndexError /
  wrong-target nudges) and undo/redo bound to the discarded project
  (permanently dead); both are rebound now.
- Undo/redo now revert the working buffer together with the canvas
  (previously Enter after `u` saved the edit you had just undone), and
  saving no longer records a bogus history entry that destroyed the redo
  stack.
- Ctrl+G/Ctrl+A/Ctrl+V/Ctrl+R were swallowed by the plain-key branches in
  edit mode (Ctrl+G opened the send menu instead of snapping); Alt+arrows
  now actually detaches as documented; Ctrl+G snap / Ctrl+L align and the
  `g` send now reach the working buffer and the undo history.
- Ctrl+drag now builds its rewrite against the working buffer when an edit
  session is open (a disk-based proposal silently dropped pending edits and
  the follow-up Ctrl+S clobbered the applied drag); the no-dialog Ctrl+S
  path now acknowledges its own write instead of triggering a self-reload.
- Right-click no longer permanently retargets later keyboard adds, and
  context-menu popovers are unparented on close instead of leaking.

### MCP server

- `set_field`/`set_fields` type coercion was dead code under PEP 563
  (string annotations): Measure dicts were stored raw (project poisoned,
  `save` crashed later), `"64"` stayed a string, `"false"` stayed truthy.
  Coercion now resolves string annotations and parses booleans strictly.
- History integrity: snapshots are now taken only after validation, so a
  failed call no longer burns an undo level and wipes the redo stack;
  `set_project_metadata` is genuinely undoable (History snapshots project
  metadata alongside components); all-invalid `add_components` batches no
  longer record.
- `connect` honors a one-sided `from_pin`/`to_pin` (previously both were
  silently discarded); `set_value` validates enums via `dataclasses.replace`
  instead of raw setattr; `add_wire`/`connect` reject bad colors at the
  call; `snap_to_grid` rejects `grid <= 0`; `duplicate_component` and
  renames reject name collisions; `align` de-duplicates repeated names
  (they double-moved components); `save`/`render_svg`/`render_png` with
  both `path` and `return_content=True` now write the file *and* return
  content (previously the file was silently skipped); `to_json` includes
  `grid_inches`/`dot_spacing`.

### Editor / CLI

- `propose_add`/duplicate emitted `size=mm(5.0)`-style keywords without
  importing the measure helpers — the rewritten layout crashed with
  `NameError` on the next reload.
- `pydiylc convert x.json` now preserves `grid_inches`/`dot_spacing`, and
  converting to `.png` without pycairo reports a clean error instead of a
  traceback.

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
