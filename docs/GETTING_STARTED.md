# Getting started with pydiylc — for absolute beginners

This guide assumes you've never used Python virtual environments before. By
the end, you'll have a working pydiylc editor open on your machine and a
small circuit layout you built yourself.

Estimated time: **15 minutes.**

---

## What pydiylc is, in one sentence

It's a **Wayland-friendly editor for circuit layouts** — perfboards, stripboards,
pedals, that kind of thing — where the layout is a Python file you can edit
either by typing code or by clicking around a graphical canvas. It reads and
writes the same `.diy` files DIYLC uses.

You do not need to be a Python programmer. The viewer can do everything from
its GUI; the Python source is what gets saved.

---

## Step 1 — Make sure you have Python 3.10 or newer

Open a terminal and run:

```
python3 --version
```

You should see something like `Python 3.11.4`. If the number is below 3.10,
update Python first (your distro's package manager handles it; on macOS use
[python.org's installer](https://www.python.org/downloads/) or `brew install python`).

---

## Step 2 — Install the system libraries the GUI needs

The viewer uses GTK 4 and Cairo. These are not Python packages — they're system
libraries Python wraps around. Install them with your distro's package manager:

**Arch Linux / Manjaro:**
```
sudo pacman -S gtk4 python-gobject cairo
```

**Debian / Ubuntu / Mint:**
```
sudo apt install python3-gi gir1.2-gtk-4.0 libcairo2-dev libgirepository1.0-dev
```

**Fedora:**
```
sudo dnf install python3-gobject gtk4 cairo-devel gobject-introspection-devel
```

**macOS (with Homebrew):**
```
brew install gtk4 pygobject3 cairo
```

If you don't install these, pydiylc still works as a Python library (you can
write/read `.diy` files in code), but `pydiylc-view` won't open.

---

## Step 3 — Get pydiylc itself

In a terminal, pick a folder where you keep projects and:

```
cd ~/projects                # or wherever you want it
git clone https://github.com/DeepReef11/pydiylc.git
cd pydiylc
```

You're now inside the pydiylc folder. Every command below is run from here.

---

## Step 4 — Create a virtual environment ("venv")

### What is a venv?

A virtual environment is **a private folder for Python packages**, so that
when you `pip install` something for pydiylc, it doesn't get mixed up with
packages your system or other projects use. Think of it like a separate
toolbox just for this project.

Create one:

```
python3 -m venv .venv
```

This creates a `.venv/` folder inside `pydiylc/`. You only need to do this
**once per checkout** — the folder is your isolated Python.

### Activate it

Every time you open a new terminal and want to work with pydiylc, you
need to **activate** the venv:

```
source .venv/bin/activate
```

(On Windows: `.venv\Scripts\activate`.)

You'll know it worked because your prompt now starts with `(.venv)`.
Anything you `pip install` from this terminal goes into the venv, not
your system Python.

To leave the venv, type `deactivate`. The venv stays put — `deactivate`
just stops your current terminal from using it.

---

## Step 5 — Install pydiylc into the venv

With the venv activated:

```
pip install -e ".[viewer]"
```

What that command means:

- `pip install` — install a Python package.
- `-e` — "editable mode": install pydiylc *from this folder* so any edits
  you make to the source are immediately reflected. Useful if you ever
  want to tweak it.
- `.` — install the package in the current folder.
- `[viewer]` — also install the optional GUI dependencies (PyGObject, pycairo).

You should see a bunch of "Successfully installed …" lines.

If `pycairo` fails to build, you're probably missing the system Cairo
dev headers from Step 2.

---

## Step 6 — Open the example layout

Still in the activated venv:

```
pydiylc-view examples/layout_for_viewer.py
```

A window opens with an LPB-1 booster pedal layout (a small guitar effects
circuit). You can:

- **Scroll** to zoom in / out
- **Drag** the canvas to pan
- **Click** a component to select it
- **Press T** to enter edit mode (a side panel appears)
- **Press Q** or close the window to quit

If the window doesn't open, the most likely cause is GTK isn't installed
correctly. Run `pydiylc-view --check` to confirm:

```
pydiylc-view --check
```

If that says `GTK 4 NOT available`, redo Step 2.

---

## Step 7 — Edit a layout

Press **T** to enter edit mode. The side panel shows every component.

A handful of keys do the most-common things:

| Key | What it does |
|---|---|
| Tab / Shift-Tab | Walk through components |
| Arrow keys | Move the focused component by one perfboard hole |
| **a** | Add a new component (a fuzzy-search menu opens) |
| **v** | Edit the focused component's value (e.g. `10K` → `47K`) |
| **D** (Shift+d) | Duplicate the focused component |
| **dd** (press d twice) | Delete the focused component |
| **R** | Rotate 90° |
| **u** / Ctrl+Z | Undo |
| **U** / Ctrl+Y | Redo |
| **Enter** | Save the file |
| **T** or **Q** | Exit edit mode |

**Right-click** anywhere on the canvas to get the same options as a menu —
including "Add component here" which puts the new part exactly where you
clicked.

When you save (Enter), the example file is rewritten. You can open it in a
text editor afterward and see your changes as plain Python.

---

## Step 8 — Make your own layout

Create a file `mylayout.py` with your favorite text editor:

```python
from pydiylc import Project, PerfBoard, Resistor, SolderPad, HookupWire

def build():
    p = Project(title="My first layout", width_cm=10, height_cm=6)
    p.add(PerfBoard(name="Board1", x1=1.0, y1=1.0, x2=3.0, y2=2.5))
    p.add(SolderPad(name="P_in", x=1.2, y=1.5))
    p.add(SolderPad(name="P_out", x=2.8, y=1.5))
    p.add(Resistor(name="R1", x1=1.5, y1=1.5, x2=2.5, y2=1.5, value="10K"))
    p.add(HookupWire(name="W1", points=[(1.2, 1.5), (1.5, 1.5)]))
    return p
```

Then:

```
pydiylc-view mylayout.py
```

The viewer auto-reloads when you save the file in your text editor. You
can also just edit *in the viewer* and let it write back the changes.

**Important detail:** if you want a component to be editable through the
GUI (drag-to-move, value-edit, etc.), it must be built with keyword
arguments (`Resistor(name="R1", x1=..., y1=..., ...)`), not positional
arguments (`Resistor("R1", 1.0, 1.5, ...)`). The viewer warns you when
it can't auto-edit a component, and tells you how to rewrite it.

---

## Step 9 — Convert and export

You don't need the GUI for everything. Three handy command-line tools come
with the install:

```
pydiylc convert mylayout.py mylayout.diy     # build a .diy from Python
pydiylc convert mylayout.diy mylayout.json   # extract to JSON
pydiylc render  mylayout.py --out preview.svg
pydiylc info    mylayout.py                  # summary + warnings
```

Open the resulting `.diy` in DIYLC if you have it — pydiylc's output is
fully compatible. Or open the `.svg` in any browser.

---

## Common gotchas

- **"command not found: pydiylc-view"** — your venv isn't activated. Run
  `source .venv/bin/activate` from inside the `pydiylc/` folder.
- **The fuzzy menu opens but Enter doesn't pick** — that should be fixed.
  If it isn't, file an issue and paste the output of `pydiylc-view --check`.
- **"NameError: name 'BlankBoard' is not defined" on reload** — the
  viewer auto-imports components it adds, but if you edit by hand and
  use a name you didn't import, you'll get this. Add it to your
  `from pydiylc import …` line.
- **Dark theme settings vs. system** — pydiylc respects GTK's
  preferences. To force light or dark, click the gear icon in the header
  bar.

---

## Where to go next

- **`README.md`** — the technical overview, full keybinding tables, MCP
  server docs, all 40 component types listed.
- **`docs/keyboard-tree-editor.md`** — the design document explaining
  how the editor's mental model works (vim-like modes, the
  working-buffer save flow, the connectivity graph).
- **`LLMS.txt`** — a one-page summary for LLMs to use the library.
- **`examples/`** — more layouts to learn from.
- **`catalog.json`** — every component's exact field list and allowed
  values, in JSON. Useful for codegen.
