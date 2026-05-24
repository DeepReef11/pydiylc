"""GTK4 + Cairo viewer for pydiylc Projects.

Native Wayland-friendly, pan/zoom/click-select, optional auto-reload of a
Python file that builds a Project.

GTK4 / PyGObject is an *optional* dependency. Importing this module without
PyGObject installed raises ImportError with a helpful hint. The rest of
pydiylc has no GTK dependency.

CLI entry point::

    pydiylc-view path/to/my_layout.py
    pydiylc-view path/to/layout.json
    pydiylc-view path/to/layout.diy   # not supported yet (emit-only)

Inside a script, you can do::

    from pydiylc.viewer import show
    show(project)
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Callable

from .components import Component
from .core import Project
from . import cairo_render


def _require_gtk():
    try:
        import gi  # noqa: F401
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk, Gdk, GLib  # noqa: F401
    except (ImportError, ValueError) as exc:
        raise ImportError(
            "pydiylc.viewer requires PyGObject and GTK 4.\n"
            "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0\n"
            "  Arch:           sudo pacman -S python-gobject gtk4\n"
            "  Fedora:         sudo dnf install python3-gobject gtk4\n"
            f"(underlying error: {exc})"
        ) from exc


def has_gtk() -> bool:
    try:
        _require_gtk()
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Loaders — turn a path into a Project (and a builder callable for reload)
# ---------------------------------------------------------------------------


def _load_python(path: Path) -> tuple[Project, Callable[[], Project]]:
    """Load a Python file that builds a Project.

    The script is expected to:
    - define a top-level variable ``project`` (a Project), OR
    - define ``def build() -> Project``, OR
    - call ``Project(...).save(...)`` and we take the last Project created.
    """
    def builder() -> Project:
        spec = importlib.util.spec_from_file_location("pydiylc_userscript", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"can't load {path}")
        module = importlib.util.module_from_spec(spec)
        # Run the user script
        spec.loader.exec_module(module)
        if hasattr(module, "project") and isinstance(module.project, Project):
            return module.project
        if hasattr(module, "build") and callable(module.build):
            result = module.build()
            if isinstance(result, Project):
                return result
            raise RuntimeError(f"{path}: build() must return a Project")
        # Fall back: look for any Project instance at module scope
        candidates = [v for v in vars(module).values() if isinstance(v, Project)]
        if candidates:
            return candidates[-1]
        if hasattr(module, "main") and callable(module.main):
            try:
                result = module.main()
            except TypeError:
                result = None
            if isinstance(result, Project):
                return result
        raise RuntimeError(
            f"{path}: define a top-level `project = Project(...)` or "
            "`def build() -> Project` so the viewer can find your layout"
        )

    return builder(), builder


def _load_json(path: Path) -> tuple[Project, Callable[[], Project]]:
    def builder() -> Project:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Project.from_dict(data)

    return builder(), builder


def load(path: str | Path) -> tuple[Project, Callable[[], Project]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.suffix == ".py":
        return _load_python(p)
    if p.suffix == ".json":
        return _load_json(p)
    if p.suffix == ".diy":
        return _load_diy(p)
    raise ValueError(f"unknown file type: {p.suffix}")


def _load_diy(path: Path) -> tuple[Project, Callable[[], Project]]:
    from .reader import read_project

    def builder() -> Project:
        return read_project(path)

    return builder(), builder


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------


def show(project: Project, *, title: str = "pydiylc viewer",
         builder: Callable[[], Project] | None = None,
         watch_path: str | Path | None = None) -> None:
    """Open a GTK4 viewer window for ``project``.

    If ``builder`` is provided, pressing R or modifying ``watch_path`` will
    call ``builder()`` again and replace the displayed project.
    """
    _require_gtk()
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib

    state = _ViewerState(project=project, builder=builder, watch_path=Path(watch_path) if watch_path else None)

    app = Gtk.Application(application_id="org.pydiylc.Viewer")

    def on_activate(_app):
        win = Gtk.ApplicationWindow(application=_app)
        win.set_title(title)
        win.set_default_size(1100, 750)
        state.window = win

        header = Gtk.HeaderBar()
        win.set_titlebar(header)

        # Status bar lives at the bottom of the window, not in the header —
        # the status text changes frequently (cursor coords, mode hints) and
        # is easier to read on a wide widget at the foot of the canvas.
        state.status_lbl = Gtk.Label(label=_status_text(state))
        state.status_lbl.set_xalign(0.0)
        state.status_lbl.add_css_class("dim-label")
        state.status_lbl.set_margin_start(8)
        state.status_lbl.set_margin_end(8)
        state.status_lbl.set_margin_top(2)
        state.status_lbl.set_margin_bottom(2)

        # Toolbar buttons in the header bar (modern GTK4 convention).
        _build_header_buttons(state, header)

        # Install actions used by the right-click context menu.
        _install_viewer_actions(state, win)

        # Load preferences + apply the theme before the canvas first draws,
        # so opening in dark mode doesn't flash a white window.
        from .prefs import Prefs
        state.prefs = Prefs.load()
        _apply_prefs(state)

        # Main content: canvas in a scrolled window
        sw = Gtk.ScrolledWindow()
        sw.set_hexpand(True)
        sw.set_vexpand(True)

        canvas = Gtk.DrawingArea()
        canvas.set_draw_func(_make_draw_func(state))
        _size_canvas_to_project(state.project, canvas)
        state.canvas = canvas

        # Mouse handlers
        click = Gtk.GestureClick()
        click.set_button(0)  # any
        click.connect("pressed", _make_click_handler(state, canvas))
        canvas.add_controller(click)

        # Right-click → context menu.
        rclick = Gtk.GestureClick()
        rclick.set_button(3)  # right mouse button
        rclick.connect("pressed", _make_right_click_handler(state, canvas))
        canvas.add_controller(rclick)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", _make_drag_begin(state))
        drag.connect("drag-update", _make_drag_update(state, canvas))
        drag.connect("drag-end", _make_drag_end(state, canvas))
        canvas.add_controller(drag)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", _make_scroll_handler(state, canvas))
        canvas.add_controller(scroll)

        # Track cursor position so we can show project coordinates in the
        # status bar.
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", _make_motion_handler(state))
        motion.connect("leave", lambda _c: (_clear_cursor(state),))
        canvas.add_controller(motion)

        sw.set_child(canvas)

        # Side panel (tree editor) + canvas in a horizontal Paned. The panel
        # is built collapsed/hidden; pressing T toggles it.
        panel = _build_tree_panel(state)
        state.tree_panel = panel
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(panel)
        paned.set_end_child(sw)
        # 340 fits "PerfBoard  ·  10x8 in" and indented node labels without
        # clipping in the common case; the user can still drag the splitter.
        paned.set_position(340)
        paned.set_resize_start_child(False)
        state.paned = paned
        panel.set_visible(False)  # hidden until T

        # Bottom status bar: thin separator + label.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.append(paned)
        outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        outer.append(state.status_lbl)
        win.set_child(outer)

        # Fit the project to the viewport once the canvas is realized so the
        # user opens to a sensible view rather than a corner of a 2200×1600
        # canvas.
        GLib.idle_add(lambda: (_fit_to_page(state), False)[1])

        # Keyboard shortcuts. Use the CAPTURE phase so we see keys before
        # GTK's default focus traversal — otherwise Tab/Shift-Tab would be
        # consumed for widget focus and never reach the tree-editor handler.
        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", _make_key_handler(state, canvas, win))
        win.add_controller(key)

        # File watcher: poll mtime every 500ms (cheap and portable).
        if state.watch_path is not None and state.builder is not None:
            state.last_mtime = state.watch_path.stat().st_mtime
            GLib.timeout_add(500, _make_poller(state))

        # Save-on-quit guard: if the buffer has unsaved changes, intercept
        # the close and ask before discarding them.
        win.connect("close-request", _make_close_request_handler(state))

        win.present()

    app.connect("activate", on_activate)
    app.run([])


class _ViewerState:
    """Mutable viewer state. Single source of truth for the GTK callbacks."""

    def __init__(self, project: Project, builder: Callable[[], Project] | None,
                 watch_path: Path | None):
        self.project = project
        self.builder = builder
        self.watch_path = watch_path
        self.last_mtime: float = 0.0
        self.zoom: float = 1.0
        self.pan_x: float = 30.0
        self.pan_y: float = 30.0
        # Multi-selection. `selected_names` is the primary set; everything
        # the user sees as selected lives here. `selected_name` mirrors the
        # most-recently-clicked entry so single-target operations (popovers,
        # status line, tree cursor sync) keep their familiar single-name
        # interface — bulk operations read `selected_names` directly.
        self.selected_names: set[str] = set()
        self.selected_name: str | None = None
        self.last_drag_pan: tuple[float, float] | None = None
        # Component-move state. When the user Ctrl+drags, this holds the
        # component being dragged plus its original anchor so we can compute
        # deltas live and propose the final move on drag-end.
        self.moving_component = None
        self.moving_orig_anchor: tuple[float, float] | None = None
        self.last_drag_delta: tuple[float, float] = (0.0, 0.0)
        # Rubber-band select state. When the user left-drags from empty
        # canvas (no Ctrl), we track the rectangle's start point in pixel
        # space and the selection that was in place when the drag began,
        # so Shift/Ctrl modifier rules combine cleanly with the marquee.
        self.rubber_band: tuple[float, float, float, float] | None = None
        self.rubber_band_base: set[str] = set()
        self.rubber_band_mode: str = "replace"  # "replace" | "add" | "toggle"
        # Tree-editor mode.
        self.tree_mode: bool = False
        self.nav = None  # tree_editor.NavState, lazily built
        self.history = None  # history.History, built on entering tree mode
        self.pending_d: bool = False  # first 'd' of a 'dd' delete chord
        # Live cursor position in project inches (None when off canvas).
        self.cursor_in: tuple[float, float] | None = None
        # One-shot placement target for the next add (set by right-click Add
        # Here, cleared after use). When None, add uses cursor_in or focused.
        self.next_add_at: tuple[float, float] | None = None
        # Page-sheet color (RGB), set by _apply_theme.
        self.page_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
        # Canvas off-page backdrop color (RGB), set by _apply_theme.
        self.canvas_backdrop: tuple[float, float, float] = (0.97, 0.97, 0.97)
        # Active right-click context popover (so callbacks can dismiss it).
        self.context_popover = None
        # Set True once the user has confirmed a close past the unsaved-
        # changes dialog; lets the close-request handler return without
        # re-prompting.
        self.quitting: bool = False
        # Working-buffer save flow.
        self.buffer = None  # buffer.Buffer (one per tree-mode session)
        self.prefs = None  # prefs.Prefs (loaded lazily)
        # Filled in by show()
        self.canvas = None
        self.status_lbl = None
        self.window = None
        self.tree_panel = None
        self.paned = None
        self.tree_listbox = None
        self.panel_hint_label = None
        self.error_msg: str | None = None


def _status_text(state: _ViewerState) -> str:
    n = len(state.project.components)
    title = state.project.title or "untitled"
    mode = "✎ EDIT  ·  " if state.tree_mode else ""
    if len(state.selected_names) > 1:
        sel = f"  ·  sel: {len(state.selected_names)} components"
    elif state.selected_name:
        sel = f"  ·  sel: {state.selected_name}"
    else:
        sel = ""
    err = f"  ·  ⚠ {state.error_msg}" if state.error_msg else ""
    chord = "  ·  d… (press d again to delete)" if state.pending_d else ""
    undo = ""
    if state.tree_mode and state.history is not None:
        bits = []
        if state.history.can_undo():
            bits.append(f"undo×{state.history.depth()}")
        if state.history.can_redo():
            bits.append(f"redo×{state.history.redo_depth()}")
        if bits:
            undo = "  ·  " + " ".join(bits)
    dirty = ""
    if state.tree_mode and state.buffer is not None and state.buffer.is_dirty:
        dirty = "  ·  ● unsaved"
    cur = ""
    if state.cursor_in is not None:
        cur = f"  ·  ({state.cursor_in[0]:.2f}, {state.cursor_in[1]:.2f}) in"
    # Duplicate-name warning: the AST surgery in edit.py finds components by
    # name; if two share a name, moves on one accidentally affect the other.
    dup = ""
    if state.tree_mode:
        from .tree_editor import duplicate_names
        dups = duplicate_names(state.project)
        if dups:
            dup = f"  ·  ⚠ duplicate names: {', '.join(dups[:3])}"
            if len(dups) > 3:
                dup += f" (+{len(dups) - 3} more)"
    return (
        f"{mode}{title}  ·  {n} components  ·  zoom {state.zoom:.2f}"
        f"{cur}{sel}{undo}{dirty}{chord}{dup}{err}"
    )


def _make_close_request_handler(state: _ViewerState):
    """Return True to cancel the close, False to allow it.

    When the buffer has unsaved changes, pops a Save / Discard / Cancel
    dialog. Save → flush then close; Discard → close without saving;
    Cancel → stay open. ``state.quitting`` short-circuits the guard after
    we've decided to close so the dialog doesn't loop.
    """
    def on_close(win):
        buf = state.buffer
        if state.quitting or buf is None or not buf.is_dirty:
            return False  # allow close
        _unsaved_changes_dialog(state, win)
        return True  # block close; dialog will re-trigger when ready
    return on_close


def _unsaved_changes_dialog(state: _ViewerState, parent_win) -> None:
    """Save / Discard / Cancel dialog for the quit guard."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    buf = state.buffer
    win = Gtk.Window()
    win.set_title("Unsaved changes")
    win.set_default_size(520, 220)
    win.set_transient_for(parent_win)
    win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(14); box.set_margin_bottom(14)
    box.set_margin_start(14); box.set_margin_end(14)

    heading = Gtk.Label(label=f"{buf.path.name} has unsaved changes")
    heading.set_xalign(0.0)
    heading.add_css_class("heading")
    box.append(heading)

    detail = Gtk.Label(
        label="Save the working buffer before closing?\n\n"
              "Save:    write the buffer to disk, then close.\n"
              "Discard: close without writing — your in-memory edits are lost.\n"
              "Cancel:  keep the window open."
    )
    detail.set_xalign(0.0)
    detail.set_wrap(True)
    box.append(detail)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    discard_btn = Gtk.Button(label="Discard")
    discard_btn.add_css_class("destructive-action")
    cancel_btn = Gtk.Button(label="Cancel  (Esc)")
    save_btn = Gtk.Button(label="Save  (Enter)")
    save_btn.add_css_class("suggested-action")

    def do_save_and_close():
        try:
            buf.flush()
        except OSError as exc:
            _info_dialog(state.window, "Save failed", str(exc))
            return
        state.quitting = True
        win.close()
        parent_win.close()

    def do_discard_and_close():
        state.quitting = True
        win.close()
        parent_win.close()

    save_btn.connect("clicked", lambda _b: do_save_and_close())
    discard_btn.connect("clicked", lambda _b: do_discard_and_close())
    cancel_btn.connect("clicked", lambda _b: win.close())
    btn_box.append(discard_btn)
    btn_box.append(cancel_btn)
    btn_box.append(save_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            do_save_and_close(); return True
        if keyval == Gdk.KEY_Escape:
            win.close(); return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.set_default_widget(save_btn)
    win.present()
    save_btn.grab_focus()


def _apply_prefs(state: _ViewerState) -> None:
    """Apply preference values to live UI widgets (theme, hint visibility…)."""
    if state.prefs is None:
        return
    if state.panel_hint_label is not None:
        state.panel_hint_label.set_visible(state.prefs.show_panel_hint)
    _apply_theme(state, state.prefs.theme)


def _apply_theme(state: _ViewerState, theme: str) -> None:
    """Switch the GTK system theme between light/dark/system-default.

    The component-page itself stays white in both themes — it's the
    "sheet of paper on the desk" affordance every CAD tool uses, and
    keeps component label text legible regardless of theme. What changes
    in dark mode is the chrome: header bar, side panel, status bar,
    canvas off-page area, dialogs.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    if theme == "dark":
        settings.set_property("gtk-application-prefer-dark-theme", True)
    elif theme == "light":
        settings.set_property("gtk-application-prefer-dark-theme", False)
    # "system" → leave alone, GTK picks based on the desktop's color scheme.

    # The canvas off-page color is drawn by us; pick a tone matching the
    # current chrome so the page-on-desk look reads right.
    state.canvas_backdrop = _canvas_backdrop_for(theme)
    state.page_color = _page_color_for(theme)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _canvas_backdrop_for(theme: str) -> tuple[float, float, float]:
    """RGB triple for the off-page canvas backdrop, per theme."""
    if theme == "dark":
        # Deep neutral with a faint purple bias so the page sheet sits on a
        # cohesive dark "desk" instead of plain charcoal.
        return (0.13, 0.12, 0.16)
    # light + system both render with a near-white desk so default GTK light
    # styling doesn't clash. (Detecting "system" actually-dark would need
    # querying GtkSettings; left for later.)
    return (0.97, 0.97, 0.97)


def _page_color_for(theme: str) -> tuple[float, float, float]:
    """RGB triple for the project-page 'sheet' background, per theme.

    Light mode keeps a true white sheet (the CAD convention — labels stay
    legible). Dark mode tints the sheet a muted dark purple so the desk
    and sheet read together; component labels are still bright enough on
    this background to remain readable.
    """
    if theme == "dark":
        return (0.20, 0.18, 0.26)
    return (1.0, 1.0, 1.0)


def _open_export_dialog(state: _ViewerState) -> None:
    """File picker that renders the current project to SVG or PNG.

    Uses ``Gtk.FileDialog.save`` (GTK4 4.10+). The extension determines the
    format (.svg or .png). Errors are surfaced through _info_dialog.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gio

    project = state.project
    suggested = "layout.svg"
    if state.watch_path is not None:
        suggested = state.watch_path.with_suffix(".svg").name

    dlg = Gtk.FileDialog()
    dlg.set_title("Export project")
    dlg.set_initial_name(suggested)

    def on_done(_d, result):
        try:
            gfile = dlg.save_finish(result)
        except Exception:
            return  # user cancelled or backend error
        if gfile is None:
            return
        path = gfile.get_path()
        if not path:
            return
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "svg"
        try:
            if ext == "png":
                from .cairo_render import render_png
                render_png(project, path)
            else:
                from .svg import render_svg_file
                # default extension is .svg if user didn't add one
                if "." not in path:
                    path += ".svg"
                render_svg_file(project, path)
        except ImportError as exc:
            _info_dialog(state.window, "Export failed", str(exc))
            return
        except OSError as exc:
            _info_dialog(state.window, "Export failed", str(exc))
            return
        _info_dialog(state.window, "Exported", f"Wrote {path}")

    dlg.save(state.window, None, on_done)


def _open_prefs_dialog(state: _ViewerState) -> None:
    """Modal preferences window with checkboxes for the toggleable settings.

    Loads prefs if they haven't been loaded yet (so Preferences works
    outside edit mode too), persists on Save.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
    from .prefs import Prefs

    if state.prefs is None:
        state.prefs = Prefs.load()

    win = Gtk.Window()
    win.set_title("Preferences")
    win.set_default_size(420, 220)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(14); box.set_margin_bottom(14)
    box.set_margin_start(14); box.set_margin_end(14)

    heading = Gtk.Label(label="Preferences")
    heading.set_xalign(0.0)
    heading.add_css_class("heading")
    box.append(heading)

    save_dialog_chk = Gtk.CheckButton(
        label="Show save-diff dialog on Ctrl+S"
    )
    save_dialog_chk.set_active(state.prefs.show_save_dialog)
    box.append(save_dialog_chk)

    panel_hint_chk = Gtk.CheckButton(
        label="Show keyboard hint at the bottom of the edit panel"
    )
    panel_hint_chk.set_active(state.prefs.show_panel_hint)
    box.append(panel_hint_chk)

    # Theme picker (radio buttons). The page itself stays white in both
    # themes (CAD convention); only the chrome darkens.
    theme_label = Gtk.Label(label="Theme:")
    theme_label.set_xalign(0.0)
    box.append(theme_label)
    theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    light_rb = Gtk.CheckButton(label="Light")
    dark_rb = Gtk.CheckButton(label="Dark")
    sys_rb = Gtk.CheckButton(label="System")
    dark_rb.set_group(light_rb)
    sys_rb.set_group(light_rb)
    {"light": light_rb, "dark": dark_rb, "system": sys_rb}[
        state.prefs.theme if state.prefs.theme in ("light", "dark", "system") else "system"
    ].set_active(True)
    theme_box.append(light_rb)
    theme_box.append(dark_rb)
    theme_box.append(sys_rb)
    box.append(theme_box)

    path_label = Gtk.Label(
        label=f"Saved to {state.prefs._path}" if state.prefs._path else ""
    )
    path_label.set_xalign(0.0)
    path_label.add_css_class("dim-label")
    path_label.set_wrap(True)
    box.append(path_label)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    save_btn = Gtk.Button(label="Save  (Enter)")
    save_btn.add_css_class("suggested-action")

    def do_save():
        state.prefs.show_save_dialog = save_dialog_chk.get_active()
        state.prefs.show_panel_hint = panel_hint_chk.get_active()
        if dark_rb.get_active():
            state.prefs.theme = "dark"
        elif light_rb.get_active():
            state.prefs.theme = "light"
        else:
            state.prefs.theme = "system"
        state.prefs.save()
        _apply_prefs(state)
        win.close()

    cancel_btn.connect("clicked", lambda _b: win.close())
    save_btn.connect("clicked", lambda _b: do_save())
    btn_box.append(cancel_btn)
    btn_box.append(save_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            do_save(); return True
        if keyval == Gdk.KEY_Escape:
            win.close(); return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.set_default_widget(save_btn)
    win.present()
    save_btn.grab_focus()


def _install_viewer_actions(state: _ViewerState, win) -> None:
    """Bind the context-menu actions (rotate / delete / send / add / focus).

    Each closes the popover (if any) and routes to the same handlers the
    keyboard shortcuts already use. Tree mode is auto-entered for actions
    that require it, so right-click works without first pressing T.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio

    def ensure_tree():
        if not state.tree_mode:
            _enter_tree_mode(state)

    def with_popover(action):
        def wrapper(_a, _p):
            if state.context_popover is not None:
                state.context_popover.popdown()
                state.context_popover = None
            ensure_tree()
            action()
        return wrapper

    group = Gio.SimpleActionGroup()
    for name, fn in [
        ("rotate", lambda: _tree_rotate(state, clockwise=True)),
        ("delete", lambda: _tree_delete(state)),
        ("send", lambda: _open_fuzzy_menu(state, mode="send")),
        ("add", lambda: _open_add_menu(state, autowire=False)),
        ("focus", lambda: _open_fuzzy_menu(state, mode="focus")),
        ("edit_value", lambda: _open_edit_value_dialog(state)),
        ("duplicate", lambda: _tree_duplicate(state)),
    ]:
        a = Gio.SimpleAction.new(name, None)
        a.connect("activate", with_popover(fn))
        group.add_action(a)
    win.insert_action_group("viewer", group)


_KEYBINDINGS: list[tuple[str, list[tuple[str, str]]]] = [
    ("View", [
        ("scroll", "zoom"),
        ("drag", "pan"),
        ("0", "fit page to viewport"),
        ("+/-", "zoom in/out"),
        ("click", "select component"),
        ("Ctrl+click", "toggle component in/out of multi-selection"),
        ("Shift+click", "add component to multi-selection"),
        ("drag (empty)", "rubber-band rectangle select"),
        ("Shift+drag (empty)", "rubber-band, add to existing selection"),
        ("right-click", "context menu (Add here, Edit value, …)"),
        ("Ctrl+drag", "drag a component (proposes a source edit on release)"),
    ]),
    ("Modes", [
        ("T", "toggle edit mode"),
        ("Q / Esc", "exit edit mode"),
        ("?", "this help dialog"),
        ("r", "reload from disk"),
    ]),
    ("Edit mode — navigation", [
        ("Tab / Shift-Tab", "next / previous component (or nodes once drilled)"),
        ("Space", "drill into / out of the focused component's nodes"),
        ("PgUp / PgDn", "page 10 components at a time"),
        ("/", "fuzzy-search to focus any node"),
        ("g", "fuzzy-search to send the focused node onto another node"),
    ]),
    ("Edit mode — modify", [
        ("arrows", "move focused node by one board hole (grid step off-board)"),
        ("Ctrl+arrows", "nudge by one grid step"),
        ("Ctrl+Shift+arrows", "fine nudge (1/10 grid)"),
        ("R / Shift+R", "rotate 90° CW / CCW (each selected if multi-sel)"),
        ("v", "edit value/text/resistance (applies to every multi-selected component with that field)"),
        ("a", "add a component (auto-wires to focused pin)"),
        ("A", "add a component without auto-wiring"),
        ("D", "duplicate the focused component (or all multi-selected; clones become the new selection)"),
        ("dd", "delete the focused component (or all multi-selected, press d twice)"),
        ("arrows (multi-sel)", "nudge every multi-selected component together"),
    ]),
    ("History", [
        ("u / Ctrl+Z", "undo"),
        ("U / Ctrl+Y", "redo"),
    ]),
    ("Save", [
        ("Enter", "write the working buffer to disk (silent)"),
        ("Ctrl+S", "save with the diff-on-save dialog"),
    ]),
]


def _open_help_dialog(state: _ViewerState) -> None:
    """Which-key-style popup listing every keyboard shortcut.

    Renders the _KEYBINDINGS table as a two-column "key | action" grid
    per group. Esc / Enter / ? close it.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    win = Gtk.Window()
    win.set_title("Keyboard shortcuts")
    win.set_default_size(640, 600)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.set_margin_top(12); outer.set_margin_bottom(12)
    outer.set_margin_start(12); outer.set_margin_end(12)

    heading = Gtk.Label(label="Keyboard shortcuts")
    heading.set_xalign(0.0)
    heading.add_css_class("title-2")
    outer.append(heading)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    body.set_margin_top(4); body.set_margin_bottom(4)
    body.set_margin_start(4); body.set_margin_end(4)

    for group_name, bindings in _KEYBINDINGS:
        group_lbl = Gtk.Label(label=group_name)
        group_lbl.set_xalign(0.0)
        group_lbl.add_css_class("heading")
        body.append(group_lbl)
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(2)
        for row, (key, desc) in enumerate(bindings):
            key_lbl = Gtk.Label(label=key)
            key_lbl.set_xalign(0.0)
            key_lbl.add_css_class("monospace")
            key_lbl.add_css_class("accent")
            desc_lbl = Gtk.Label(label=desc)
            desc_lbl.set_xalign(0.0)
            desc_lbl.set_wrap(True)
            grid.attach(key_lbl, 0, row, 1, 1)
            grid.attach(desc_lbl, 1, row, 1, 1)
        body.append(grid)
    sw.set_child(body)
    outer.append(sw)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    close_btn = Gtk.Button(label="Close  (Esc)")
    close_btn.connect("clicked", lambda _b: win.close())
    btn_box.append(close_btn)
    outer.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter,
                      Gdk.KEY_question, Gdk.KEY_slash):  # ? and / both close
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(outer)
    win.set_default_widget(close_btn)
    win.present()
    close_btn.grab_focus()


def _build_header_buttons(state: _ViewerState, header) -> None:
    """Populate the HeaderBar with toolbar buttons.

    Modern GTK4 convention is to keep top-level actions on the title bar
    rather than a separate toolbar widget. Each button mirrors a keyboard
    shortcut so power users keep their muscle memory.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    def btn(icon: str, tooltip: str, on_click):
        b = Gtk.Button.new_from_icon_name(icon)
        b.set_tooltip_text(tooltip)
        b.connect("clicked", lambda _b: on_click())
        return b

    def sep():
        s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        s.set_margin_start(4); s.set_margin_end(4)
        return s

    # Left cluster — modal switches.
    header.pack_start(btn("view-list-symbolic", "Toggle edit mode (T)",
        lambda: _enter_tree_mode(state) if not state.tree_mode else _exit_tree_mode(state)))
    header.pack_start(btn("list-add-symbolic", "Add component (a)",
        lambda: _open_add_menu(state, autowire=False) if state.tree_mode else None))
    header.pack_start(sep())
    header.pack_start(btn("preferences-system-symbolic", "Preferences",
        lambda: _open_prefs_dialog(state)))
    header.pack_start(btn("document-send-symbolic", "Export to SVG / PNG",
        lambda: _open_export_dialog(state)))
    header.pack_start(btn("help-faq-symbolic", "Keyboard shortcuts (?)",
        lambda: _open_help_dialog(state)))

    # Right cluster — view + history + save. pack_end appends right-to-left,
    # so the visual order is: undo · redo · | · save · save-as · | · zoom out · in · fit.
    header.pack_end(btn("zoom-fit-best-symbolic", "Fit page to viewport (0)",
        lambda: _fit_to_page(state)))
    header.pack_end(btn("zoom-in-symbolic", "Zoom in (+)",
        lambda: _zoom_by(state, 1.2)))
    header.pack_end(btn("zoom-out-symbolic", "Zoom out (-)",
        lambda: _zoom_by(state, 1 / 1.2)))
    header.pack_end(sep())
    header.pack_end(btn("document-save-as-symbolic", "Save with diff dialog (Ctrl+S)",
        lambda: _save_buffer(state) if state.buffer else None))
    header.pack_end(btn("document-save-symbolic", "Save (Enter)",
        lambda: _flush_buffer_silent(state) if state.buffer else None))
    header.pack_end(sep())
    header.pack_end(btn("edit-redo-symbolic", "Redo (U / Ctrl+Y)",
        lambda: _tree_redo(state)))
    header.pack_end(btn("edit-undo-symbolic", "Undo (u / Ctrl+Z)",
        lambda: _tree_undo(state)))


def _zoom_by(state: _ViewerState, factor: float) -> None:
    state.zoom = max(0.1, min(10.0, state.zoom * factor))
    if state.canvas is not None:
        state.canvas.queue_draw()
    _refresh_status(state)


def _size_canvas_to_project(project, canvas) -> None:
    """Set the DrawingArea's content size to fit the project at 1:1 zoom
    with a comfortable scrollable margin.

    A fixed 2200×1600 canvas wastes space for small layouts and is too small
    for large ones. Sizing to (project + margin) lets the ScrolledWindow's
    scrollbars represent the actual editing surface.
    """
    w_in = project.width_cm / 2.54
    h_in = project.height_cm / 2.54
    margin = 200
    canvas.set_content_width(int(w_in * cairo_render.PX_PER_INCH + 2 * margin))
    canvas.set_content_height(int(h_in * cairo_render.PX_PER_INCH + 2 * margin))


def _fit_to_page(state: _ViewerState) -> None:
    """Set pan+zoom so the project bounds fill the canvas viewport."""
    canvas = state.canvas
    if canvas is None:
        return
    vw = canvas.get_width()
    vh = canvas.get_height()
    if vw <= 0 or vh <= 0:
        return
    project = state.project
    w_in = project.width_cm / 2.54
    h_in = project.height_cm / 2.54
    page_w = w_in * cairo_render.PX_PER_INCH
    page_h = h_in * cairo_render.PX_PER_INCH
    if page_w <= 0 or page_h <= 0:
        return
    margin = 30
    zoom_x = (vw - 2 * margin) / page_w
    zoom_y = (vh - 2 * margin) / page_h
    state.zoom = max(0.1, min(10.0, min(zoom_x, zoom_y)))
    # Center the page in the viewport.
    state.pan_x = (vw - page_w * state.zoom) / 2
    state.pan_y = (vh - page_h * state.zoom) / 2
    canvas.queue_draw()
    _refresh_status(state)


def _refresh_status(state: _ViewerState) -> None:
    if state.status_lbl is not None:
        state.status_lbl.set_text(_status_text(state))


def _make_draw_func(state: _ViewerState):
    def draw(area, cr, width, height):
        # Off-page backdrop (changes with the theme).
        cr.set_source_rgb(*state.canvas_backdrop)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.save()
        cr.translate(state.pan_x, state.pan_y)
        cr.scale(state.zoom, state.zoom)
        cairo_render.draw_project(
            cr,
            state.project,
            scale=cairo_render.PX_PER_INCH,
            background=state.page_color,
            show_grid=True,
            selected_names=state.selected_names,
            focus_pin=_focused_pin_position(state) if state.tree_mode else None,
        )
        # Rubber-band marquee, drawn in project pixel coords so it sits
        # inside the same pan/zoom transform as the components.
        if state.rubber_band is not None:
            rx1, ry1, rx2, ry2 = state.rubber_band
            x = min(rx1, rx2); y = min(ry1, ry2)
            w = abs(rx2 - rx1); h = abs(ry2 - ry1)
            # Translucent fill.
            cr.set_source_rgba(0.30, 0.55, 0.95, 0.18)
            cr.rectangle(x, y, w, h)
            cr.fill_preserve()
            # Dashed border.
            cr.set_source_rgba(0.20, 0.45, 0.90, 0.9)
            cr.set_line_width(1.0 / state.zoom)
            cr.set_dash([4.0 / state.zoom, 3.0 / state.zoom])
            cr.stroke()
            cr.set_dash([])
        cr.restore()
    return draw


def _project_xy_from_screen(state: _ViewerState, sx: float, sy: float) -> tuple[float, float]:
    """Inverse of the canvas transform — used for click hit-testing."""
    cx = (sx - state.pan_x) / state.zoom
    cy = (sy - state.pan_y) / state.zoom
    return cx, cy


def _make_click_handler(state: _ViewerState, canvas):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk

    def on_click(gesture, n_press, x, y):
        cx, cy = _project_xy_from_screen(state, x, y)
        hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
        mods = gesture.get_current_event_state()
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        _apply_click_selection(state, hit, ctrl=ctrl, shift=shift)
        if hit is not None and state.tree_mode and state.nav is not None:
            idx = state.project.components.index(hit)
            state.nav.focus_node(idx, None)
            _refresh_tree_panel(state)
        canvas.queue_draw()
        _refresh_status(state)
    return on_click


def _apply_click_selection(state: _ViewerState, hit, *,
                           ctrl: bool, shift: bool) -> None:
    """Update selection state for one click. Pure function over the state
    so unit tests can exercise the selection logic without GTK.

    - Plain click on a component: replace selection.
    - Ctrl-click on a component: toggle membership.
    - Shift-click on a component: add to selection.
    - Click on empty canvas (no modifier): clear selection.
    - Click on empty canvas (Ctrl/Shift): leave selection alone.
    """
    if hit is None:
        if not (ctrl or shift):
            state.selected_names.clear()
            state.selected_name = None
        return
    name = getattr(hit, "name", None)
    if name is None:
        return
    if ctrl:
        if name in state.selected_names:
            state.selected_names.discard(name)
            # If we just removed the focused one, fall back to any remaining.
            if state.selected_name == name:
                state.selected_name = next(iter(state.selected_names), None)
        else:
            state.selected_names.add(name)
            state.selected_name = name
    elif shift:
        state.selected_names.add(name)
        state.selected_name = name
    else:
        state.selected_names = {name}
        state.selected_name = name


def _make_right_click_handler(state: _ViewerState, canvas):
    """Right-click pops a context menu with the most common actions."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, Gio

    def on_rclick(gesture, n_press, x, y):
        cx, cy = _project_xy_from_screen(state, x, y)
        hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
        # Select the right-clicked component (and sync tree). Right-click
        # always replaces the selection so the popover targets one part —
        # bulk operations live on left-click + modifiers.
        if hit is not None:
            name = getattr(hit, "name", None)
            if name is not None:
                state.selected_names = {name}
                state.selected_name = name
            if state.tree_mode and state.nav is not None:
                state.nav.focus_node(state.project.components.index(hit), None)
                _refresh_tree_panel(state)
            canvas.queue_draw()
            _refresh_status(state)

        # Remember the click in project inches so the upcoming Add lands here.
        state.next_add_at = (
            cx / cairo_render.PX_PER_INCH,
            cy / cairo_render.PX_PER_INCH,
        )

        menu = Gio.Menu()
        if hit is not None:
            menu.append("Edit value… (v)", "viewer.edit_value")
            menu.append("Duplicate (D)", "viewer.duplicate")
            menu.append("Rotate (R)", "viewer.rotate")
            menu.append("Delete (dd)", "viewer.delete")
            menu.append("Send to… (g)", "viewer.send")
        menu.append("Add component here…", "viewer.add")
        menu.append("Focus… (/)", "viewer.focus")

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(canvas)
        # Position at the click.
        rect = Gdk.Rectangle()
        rect.x = int(x); rect.y = int(y); rect.width = 1; rect.height = 1
        popover.set_pointing_to(rect)
        popover.set_has_arrow(False)
        popover.popup()
        # Stash so the action callbacks can dismiss it.
        state.context_popover = popover

    return on_rclick


def _make_drag_begin(state: _ViewerState):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk

    def on_begin(gesture, x, y):
        # Determine the modifier state.
        device = gesture.get_device()
        seat = device.get_seat() if device else None
        ctrl_held = False
        shift_held = False
        if seat is not None:
            kbd = seat.get_keyboard()
            if kbd is not None:
                mods = kbd.get_modifier_state()
                ctrl_held = bool(mods & Gdk.ModifierType.CONTROL_MASK)
                shift_held = bool(mods & Gdk.ModifierType.SHIFT_MASK)

        # If Ctrl is held and a hit is under the cursor, enter move-component
        # mode. Otherwise plain pan or rubber-band.
        if ctrl_held:
            cx, cy = _project_xy_from_screen(state, x, y)
            hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
            if hit is not None:
                state.moving_component = hit
                state.moving_orig_anchor = _current_anchor(hit)
                state.last_drag_delta = (0.0, 0.0)
                name = getattr(hit, "name", None)
                state.selected_name = name
                if name is not None:
                    state.selected_names = {name}
                _refresh_status(state)
                return

        # Rubber-band when the drag starts on empty canvas (no component hit).
        # If a component IS under the cursor and no modifier is held, fall
        # through to pan so the user can drag the canvas without first having
        # to find an empty spot.
        cx, cy = _project_xy_from_screen(state, x, y)
        hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
        if hit is None and not ctrl_held:
            # Empty canvas + left-drag → rubber-band select. Shift adds
            # to the existing selection; plain replaces. (Ctrl is taken
            # by the component-drag flow above.)
            state.rubber_band = (cx, cy, cx, cy)
            state.rubber_band_base = set(state.selected_names)
            state.rubber_band_mode = "add" if shift_held else "replace"
            state.last_drag_pan = None
            state.moving_component = None
            return

        state.last_drag_pan = (state.pan_x, state.pan_y)
        state.moving_component = None
    return on_begin


def _make_drag_update(state: _ViewerState, canvas):
    def on_update(gesture, dx, dy):
        if state.moving_component is not None:
            # Move-component mode. Convert pixel delta to inches via the
            # current zoom, undoing our previous delta first so the net move
            # is exactly (dx, dy) from the drag-begin point.
            inch_dx_now = dx / state.zoom / cairo_render.PX_PER_INCH
            inch_dy_now = dy / state.zoom / cairo_render.PX_PER_INCH
            prev_dx, prev_dy = state.last_drag_delta
            step_dx = inch_dx_now - prev_dx
            step_dy = inch_dy_now - prev_dy
            try:
                from .edit import move_component_inplace
                move_component_inplace(state.moving_component, step_dx, step_dy)
                state.last_drag_delta = (inch_dx_now, inch_dy_now)
            except TypeError:
                pass
            canvas.queue_draw()
            return
        if state.rubber_band is not None:
            # Update marquee rectangle and recompute selection live.
            start_x, start_y, _cur_x_prev, _cur_y_prev = state.rubber_band
            cur_x = start_x + dx / state.zoom
            cur_y = start_y + dy / state.zoom
            state.rubber_band = (start_x, start_y, cur_x, cur_y)
            _apply_rubber_band_selection(state)
            canvas.queue_draw()
            _refresh_status(state)
            return
        if state.last_drag_pan is None:
            return
        state.pan_x = state.last_drag_pan[0] + dx
        state.pan_y = state.last_drag_pan[1] + dy
        canvas.queue_draw()
    return on_update


def _apply_rubber_band_selection(state: _ViewerState) -> None:
    """Recompute selected_names from the current rubber-band rectangle.

    Pure-state helper so a unit test can drive it without GTK.
    """
    if state.rubber_band is None:
        return
    rx1, ry1, rx2, ry2 = state.rubber_band
    inside = {
        getattr(c, "name", None)
        for c in cairo_render.components_in_rect(
            state.project, rx1, ry1, rx2, ry2, cairo_render.PX_PER_INCH
        )
    }
    inside.discard(None)
    if state.rubber_band_mode == "add":
        state.selected_names = state.rubber_band_base | inside
    else:
        # "replace" — start from empty + everything inside.
        state.selected_names = set(inside)
    # Keep selected_name pointing at something sensible.
    if state.selected_name not in state.selected_names:
        state.selected_name = next(iter(state.selected_names), None)


def _make_drag_end(state: _ViewerState, canvas):
    def on_end(gesture, dx, dy):
        # Rubber-band wraps up by clearing the marquee — selection was
        # already kept in sync during drag-update.
        if state.rubber_band is not None:
            state.rubber_band = None
            state.rubber_band_base = set()
            canvas.queue_draw()
            _refresh_status(state)
            return
        if state.moving_component is None:
            return
        comp = state.moving_component
        new_anchor = _current_anchor(comp)
        orig = state.moving_orig_anchor
        # Reset move-state regardless of whether we apply.
        state.moving_component = None
        state.moving_orig_anchor = None
        state.last_drag_delta = (0.0, 0.0)
        if orig is None or new_anchor == orig:
            return
        # Snap the new anchor to the project grid (0.1 in default). Round the
        # result to 4 decimals so float noise (5.0/0.1*0.1 = 2.4000...004)
        # doesn't reach the canvas or the source rewrite.
        grid = state.project.grid_inches or 0.1
        new_x = round(round(new_anchor[0] / grid) * grid, 4)
        new_y = round(round(new_anchor[1] / grid) * grid, 4)
        # Re-align the in-memory component to the snapped anchor so the
        # preview matches what we'd write to disk.
        from .edit import move_component_inplace
        cur = _current_anchor(comp)
        try:
            move_component_inplace(comp, new_x - cur[0], new_y - cur[1])
        except TypeError:
            pass
        canvas.queue_draw()
        _propose_and_dialog(state, comp, orig, (new_x, new_y))
    return on_end


def _current_anchor(component) -> tuple[float, float]:
    """Return the component's display anchor: its first endpoint."""
    if hasattr(component, "x1") and hasattr(component, "y1"):
        return float(component.x1), float(component.y1)
    if hasattr(component, "x") and hasattr(component, "y"):
        return float(component.x), float(component.y)
    if hasattr(component, "points") and component.points:
        return float(component.points[0][0]), float(component.points[0][1])
    return 0.0, 0.0


def _propose_and_dialog(state: _ViewerState, component, orig_anchor: tuple[float, float],
                         new_anchor: tuple[float, float]) -> None:
    """Compute a source-rewrite proposal and surface a confirmation dialog.

    If the source can't be AST-edited (positional args, no file, etc.),
    show an informational dialog explaining how to apply the move manually.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    name = getattr(component, "name", None)
    summary_line = (
        f"{name or '?'}: ({orig_anchor[0]:.2f}, {orig_anchor[1]:.2f}) → "
        f"({new_anchor[0]:.2f}, {new_anchor[1]:.2f}) in"
    )

    if state.watch_path is None or state.watch_path.suffix.lower() != ".py":
        _info_dialog(
            state.window,
            "Component moved (in-memory only)",
            f"{summary_line}\n\n"
            "Source rewrite only works when the viewer was launched on a .py "
            "file. Reload to revert the move, or edit the source by hand.",
        )
        return

    if not name:
        _info_dialog(
            state.window,
            "Component moved (in-memory only)",
            f"{summary_line}\n\n"
            "This component has no `name=` argument, so the source can't be "
            "located unambiguously. Add a name and try again.",
        )
        return

    from .edit import propose_move, locate_component
    try:
        proposal = propose_move(
            state.watch_path, name, new_anchor[0], new_anchor[1],
        )
    except LookupError as exc:
        _info_dialog(state.window, "Can't auto-apply", str(exc))
        return
    except NotImplementedError:
        # The component is in the file but uses positional coords. Show the
        # same line-numbered code preview as the apply dialog, but read-only,
        # pointing at where to edit and what the new coords would be.
        try:
            loc = locate_component(state.watch_path, name)
        except LookupError as exc:
            _info_dialog(state.window, "Can't auto-apply", str(exc))
            return
        _locate_dialog(state, loc, new_anchor)
        return

    _apply_dialog(state, proposal)


def _copy_to_clipboard(widget, text: str) -> None:
    """Put ``text`` on the system clipboard via the widget's display."""
    try:
        display = widget.get_display() if widget is not None else None
        if display is None:
            return
        clipboard = display.get_clipboard()
        clipboard.set(text)
    except Exception:
        pass  # never let a clipboard failure crash a dialog


def _make_copy_button(text_provider, parent_widget, label: str = "Copy"):
    """Build a 'Copy' button that copies the result of ``text_provider()``.

    ``text_provider`` is a callable returning the string to copy (so we can
    re-render dynamic content at click time). The button label briefly
    changes to 'Copied' on success.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib

    btn = Gtk.Button(label=label)

    def on_click(_b):
        _copy_to_clipboard(parent_widget, text_provider())
        btn.set_label("Copied")
        GLib.timeout_add(1200, lambda: (btn.set_label(label), False)[1])

    btn.connect("clicked", on_click)
    return btn


def _info_dialog(parent, title: str, body: str) -> None:
    """Information / error popup with a Copy button (replaces AlertDialog)."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    win = Gtk.Window()
    win.set_title(title)
    win.set_default_size(480, 240)
    if parent is not None:
        win.set_transient_for(parent)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12); box.set_margin_bottom(12)
    box.set_margin_start(12); box.set_margin_end(12)

    heading = Gtk.Label(label=title)
    heading.set_xalign(0.0)
    heading.add_css_class("heading")
    box.append(heading)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    tv.get_buffer().set_text(body)
    sw.set_child(tv)
    box.append(sw)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    copy_btn = _make_copy_button(lambda: f"{title}\n\n{body}", win)
    close_btn = Gtk.Button(label="Close  (Esc)")
    close_btn.connect("clicked", lambda _b: win.close())
    btn_box.append(copy_btn)
    btn_box.append(close_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    win.set_child(box)
    win.set_default_widget(close_btn)
    win.present()
    close_btn.grab_focus()


def _apply_dialog(state: _ViewerState, proposal) -> None:
    """Show a modal with the line-numbered diff and Apply / Cancel buttons.

    Enter applies, Escape cancels.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    win = Gtk.Window()
    win.set_title("Apply move?")
    win.set_default_size(680, 380)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12); box.set_margin_bottom(12)
    box.set_margin_start(12); box.set_margin_end(12)

    summary = Gtk.Label(label=proposal.summary)
    summary.set_xalign(0.0)
    summary.add_css_class("heading")
    box.append(summary)

    file_info = Gtk.Label(label=f"{proposal.path}:{proposal.line}")
    file_info.set_xalign(0.0)
    file_info.add_css_class("dim-label")
    box.append(file_info)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_monospace(True)
    tv.get_buffer().set_text(_format_diff(proposal.diff_hunk))
    sw.set_child(tv)
    box.append(sw)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel")
    apply_btn = Gtk.Button(label="Apply  (Enter)")
    apply_btn.add_css_class("suggested-action")

    def do_apply():
        from .edit import apply_proposal
        apply_proposal(proposal)
        # Writing the file bumps mtime; the watcher reloads from source.
        win.close()

    copy_btn = _make_copy_button(
        lambda: f"{proposal.summary}\n{proposal.path}:{proposal.line}\n\n"
                + _format_diff(proposal.diff_hunk),
        win,
    )
    cancel_btn.connect("clicked", lambda _b: win.close())
    apply_btn.connect("clicked", lambda _b: do_apply())
    btn_box.append(copy_btn)
    btn_box.append(cancel_btn)
    btn_box.append(apply_btn)
    box.append(btn_box)

    # Enter = Apply, Escape = Cancel. CAPTURE phase so the keys reach us
    # even when a non-button widget grabs focus (e.g. clicking on the diff).
    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            do_apply()
            return True
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    win.set_child(box)
    # Make Apply the default so Enter triggers it even before focus moves.
    apply_btn.set_receives_default(True)
    win.set_default_widget(apply_btn)
    win.present()
    apply_btn.grab_focus()


def _save_dialog(state: _ViewerState) -> None:
    """Diff-on-save dialog. Save writes the buffer to disk; Cancel discards
    the dialog (buffer keeps its pending edits). A 'Don't show again'
    checkbox toggles the show_save_dialog preference.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    buf = state.buffer
    if buf is None or not buf.is_dirty:
        return

    win = Gtk.Window()
    win.set_title(f"Save {buf.path.name}?")
    win.set_default_size(720, 420)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12); box.set_margin_bottom(12)
    box.set_margin_start(12); box.set_margin_end(12)

    heading = Gtk.Label(label=f"Save {buf.path.name}")
    heading.set_xalign(0.0)
    heading.add_css_class("heading")
    box.append(heading)

    file_info = Gtk.Label(label=str(buf.path))
    file_info.set_xalign(0.0)
    file_info.add_css_class("dim-label")
    box.append(file_info)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_monospace(True)
    tv.get_buffer().set_text(buf.diff_vs_disk())
    sw.set_child(tv)
    box.append(sw)

    dont_show = Gtk.CheckButton(label="Don't show this dialog again")
    box.append(dont_show)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    copy_btn = _make_copy_button(lambda: buf.diff_vs_disk(), win)
    cancel_btn = Gtk.Button(label="Cancel")
    save_btn = Gtk.Button(label="Save  (Enter)")
    save_btn.add_css_class("suggested-action")

    def do_save():
        if dont_show.get_active() and state.prefs is not None:
            state.prefs.show_save_dialog = False
            state.prefs.save()
        buf.flush()
        if state.canvas is not None:
            state.canvas.queue_draw()
        # Acknowledge our own write so the watcher poll won't re-trigger.
        if state.watch_path is not None:
            try:
                state.last_mtime = state.watch_path.stat().st_mtime
            except OSError:
                pass
        win.close()

    cancel_btn.connect("clicked", lambda _b: win.close())
    save_btn.connect("clicked", lambda _b: do_save())
    btn_box.append(copy_btn)
    btn_box.append(cancel_btn)
    btn_box.append(save_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            do_save()
            return True
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.set_default_widget(save_btn)
    win.present()
    save_btn.grab_focus()


def _locate_dialog(state: _ViewerState, loc, new_anchor: tuple[float, float]) -> None:
    """Read-only dialog for moves we can't auto-apply.

    Shows the same line-numbered code preview as the apply dialog, points at
    the component's line, and reports the new coordinates the user would type.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    win = Gtk.Window()
    win.set_title("Can't auto-apply — edit manually")
    win.set_default_size(680, 380)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12); box.set_margin_bottom(12)
    box.set_margin_start(12); box.set_margin_end(12)

    heading = Gtk.Label(
        label=f"{loc.component_name} → ({new_anchor[0]:g}, {new_anchor[1]:g})"
    )
    heading.set_xalign(0.0)
    heading.add_css_class("heading")
    box.append(heading)

    file_info = Gtk.Label(label=f"{loc.path}:{loc.line}")
    file_info.set_xalign(0.0)
    file_info.add_css_class("dim-label")
    box.append(file_info)

    reason = Gtk.Label(label=loc.reason)
    reason.set_xalign(0.0)
    reason.set_wrap(True)
    box.append(reason)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    tv = Gtk.TextView()
    tv.set_editable(False)
    tv.set_monospace(True)
    tv.get_buffer().set_text(_format_context(loc.context, loc.line))
    sw.set_child(tv)
    box.append(sw)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    copy_btn = _make_copy_button(
        lambda: f"{loc.component_name} → ({new_anchor[0]:g}, {new_anchor[1]:g})\n"
                f"{loc.path}:{loc.line}\n\n"
                f"{loc.reason}\n\n"
                + _format_context(loc.context, loc.line),
        win,
    )
    close_btn = Gtk.Button(label="Close  (Esc)")
    close_btn.connect("clicked", lambda _b: win.close())
    btn_box.append(copy_btn)
    btn_box.append(close_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            win.close()
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    win.set_child(box)
    win.set_default_widget(close_btn)
    win.present()
    close_btn.grab_focus()


# ---------------------------------------------------------------------------
# Tree-editor panel
# ---------------------------------------------------------------------------


def _build_tree_panel(state: _ViewerState):
    """Build the side panel: a scrolled list of tree rows."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_margin_top(6); box.set_margin_bottom(6)
    box.set_margin_start(6); box.set_margin_end(6)

    title = Gtk.Label(label="Edit mode  ·  Components  (T to exit)")
    title.set_xalign(0.0)
    title.add_css_class("heading")
    box.append(title)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    state.tree_listbox = listbox
    sw.set_child(listbox)
    box.append(sw)

    hint = Gtk.Label(
        label="Tab component · Space drill · PgUp/PgDn page · arrows hole-move\n"
              "Ctrl+arrows nudge · R rotate · / focus · g send · a add+wire · A add\n"
              "v edit value · D duplicate · dd delete · u undo · U redo\n"
              "Enter save · Ctrl+S save (diff)"
    )
    hint.add_css_class("dim-label")
    hint.set_wrap(True)
    box.append(hint)
    state.panel_hint_label = hint
    return box


def _enter_tree_mode(state: _ViewerState) -> None:
    from .tree_editor import build_tree, NavState
    from .history import History
    from .buffer import Buffer
    from .prefs import Prefs

    state.nav = NavState(build_tree(state.project))
    state.history = History(state.project)
    state.pending_d = False
    # Preserve any existing buffer with unsaved changes when re-entering tree
    # mode (T off then T on should NOT silently discard edits). Only create
    # a fresh buffer when we don't already have a dirty one for this path.
    keep_buffer = (
        state.buffer is not None
        and state.buffer.path == state.watch_path
        and state.buffer.is_dirty
    )
    if not keep_buffer:
        if state.watch_path is not None and state.watch_path.suffix.lower() == ".py":
            try:
                state.buffer = Buffer.from_disk(state.watch_path)
            except OSError as exc:
                state.error_msg = f"can't load buffer: {exc}"
                state.buffer = None
        else:
            state.buffer = None
    state.prefs = Prefs.load()
    state.tree_mode = True
    if state.tree_panel is not None:
        state.tree_panel.set_visible(True)
    _apply_prefs(state)
    _refresh_tree_panel(state)


def _exit_tree_mode(state: _ViewerState) -> None:
    state.tree_mode = False
    if state.tree_panel is not None:
        state.tree_panel.set_visible(False)


def _refresh_tree_panel(state: _ViewerState) -> None:
    """Rebuild the listbox rows from nav state and sync canvas selection."""
    lb = state.tree_listbox
    nav = state.nav
    if lb is None or nav is None:
        # Headless callers (tests, scripts) hit this path — bail before
        # importing gi so the function is usable without GTK.
        _refresh_status(state)
        if state.canvas is not None:
            state.canvas.queue_draw()
        return
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    # Clear existing rows.
    child = lb.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        lb.remove(child)
        child = nxt
    # Repopulate.
    selected_row = None
    for i, row in enumerate(nav.rows):
        lbl = Gtk.Label(label=("  " + row.label) if row.is_node else row.label)
        lbl.set_xalign(0.0)
        # Ellipsize on the right when the row is too narrow for the label,
        # so a long name (e.g. a value-laden component) never spills off the
        # panel edge or pushes the row wider than the splitter position.
        from gi.repository import Pango
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_hexpand(True)
        lbl.set_tooltip_text(row.label)
        if row.is_node and not row.movable:
            lbl.add_css_class("dim-label")
        lr = Gtk.ListBoxRow()
        lr.set_child(lbl)
        lb.append(lr)
        if i == nav.cursor:
            selected_row = lr
    if selected_row is not None:
        lb.select_row(selected_row)
        # The capture-phase key controller is on the window, not on the row,
        # so grab_focus here doesn't break our shortcut routing. Focusing
        # the row asks the ScrolledWindow to scroll it into view via GTK's
        # own scroll-on-focus behavior — much more reliable than poking the
        # vadjustment directly across the re-allocation lag of a freshly
        # rebuilt listbox.
        selected_row.grab_focus()
        _scroll_into_view(lb, selected_row)
    # Sync the canvas highlight to the focused component.
    cur = nav.current
    if cur is not None:
        comp = state.project.components[cur.component_index]
        name = getattr(comp, "name", None)
        state.selected_name = name
        # Tree-mode navigation is a single-cursor model — keep the bulk
        # set in sync so the canvas highlight matches the tree focus.
        if name is not None:
            state.selected_names = {name}
        if state.canvas is not None:
            state.canvas.queue_draw()
    _refresh_status(state)


def _record(state: _ViewerState, label: str) -> None:
    if state.history is not None:
        state.history.record(label)


def _sync_buffer_move(state: _ViewerState, op) -> None:
    """Apply a MoveOp to the working buffer. No-op if no buffer is loaded.

    Failures (positional-args / missing component) are recorded in
    state.error_msg and shown in the status bar; they don't crash the edit
    since the in-memory project already changed. The user will see the
    diff-on-save dialog later and can fix the source by hand.
    """
    if state.buffer is None:
        return
    try:
        proposal = state.buffer.propose(moves=[op])
    except (LookupError, NotImplementedError) as exc:
        state.error_msg = f"buffer sync: {exc}"
        return
    if proposal is not None:
        state.buffer.apply(proposal)


def _sync_buffer_add(state: _ViewerState, component) -> None:
    """Insert a new component into the working buffer."""
    if state.buffer is None:
        return
    try:
        proposal = state.buffer.propose(adds=[component])
    except (LookupError, NotImplementedError) as exc:
        state.error_msg = f"buffer sync: {exc}"
        return
    if proposal is not None:
        state.buffer.apply(proposal)


def _sync_buffer_rotate(state: _ViewerState, component) -> None:
    """Write a rotate back to the working buffer.

    If the component has an ``orientation`` enum we write that keyword;
    otherwise (raw-coordinate rotation) we replace x1/y1/x2/y2 or
    points=[...] with the post-rotation values.
    """
    if state.buffer is None:
        return
    from .edit import KeywordOp, CoordsOp
    from .graph import control_points_of

    name = getattr(component, "name", None)
    if not name:
        return
    orientation = getattr(component, "orientation", None)
    try:
        if orientation is not None:
            proposal = state.buffer.propose(
                keyword_ops=[KeywordOp(name, "orientation", orientation)]
            )
        elif hasattr(component, "x1") and hasattr(component, "x2"):
            proposal = state.buffer.propose(
                coords_ops=[CoordsOp(name, two_pin=(component.x1, component.y1,
                                                   component.x2, component.y2))]
            )
        elif hasattr(component, "points"):
            proposal = state.buffer.propose(
                coords_ops=[CoordsOp(name, points=list(component.points))]
            )
        else:
            proposal = None
    except (LookupError, NotImplementedError) as exc:
        state.error_msg = f"buffer sync: {exc}"
        return
    if proposal is not None:
        state.buffer.apply(proposal)


def _sync_buffer_delete(state: _ViewerState, name: str) -> None:
    """Remove the component's `p.add(...)` line from the working buffer."""
    if state.buffer is None or not name:
        return
    from .edit import DeleteOp
    try:
        proposal = state.buffer.propose(deletes=[DeleteOp(name)])
    except (LookupError, NotImplementedError) as exc:
        state.error_msg = f"buffer sync: {exc}"
        return
    if proposal is not None:
        state.buffer.apply(proposal)


def _flush_buffer_silent(state: _ViewerState) -> None:
    """Write the buffer to disk with no UI. Used by Enter — the dialog is
    reserved for explicit Ctrl+S saves."""
    buf = state.buffer
    if buf is None or not buf.is_dirty:
        return
    try:
        buf.flush()
    except OSError as exc:
        _info_dialog(state.window, "Save failed", str(exc))
        return
    if state.history is not None:
        state.history.record("save")
    if state.canvas is not None:
        state.canvas.queue_draw()
    if state.watch_path is not None:
        try:
            state.last_mtime = state.watch_path.stat().st_mtime
        except OSError:
            pass
    _refresh_status(state)


def _save_buffer(state: _ViewerState) -> None:
    """Save the working buffer to disk, gated by the save dialog preference.

    When ``prefs.show_save_dialog`` is True we open the diff dialog with a
    'don't show again' checkbox; otherwise we flush directly. No-op if the
    buffer is clean or absent.
    """
    buf = state.buffer
    if buf is None:
        _info_dialog(
            state.window, "No buffer",
            "No editable working buffer for this source — only .py layouts "
            "support the save flow today.",
        )
        return
    if not buf.is_dirty:
        return  # nothing to do
    if state.prefs is not None and not state.prefs.show_save_dialog:
        if buf.flush():
            state.history.record("save") if state.history is not None else None
        if state.canvas is not None:
            state.canvas.queue_draw()
        return
    _save_dialog(state)


def _tree_move(state: _ViewerState, dx: float, dy: float) -> None:
    """Apply a literal nudge to the focused component or node. If a
    multi-selection (N>1) is active, every selected component's body
    shifts by (dx, dy) in a single snapshot.
    """
    from . import moves
    from .edit import MoveOp
    from .graph import control_points_of

    nav = state.nav
    if nav is None or nav.current is None:
        return

    # Bulk path: nudge every selected component as a group.
    if len(state.selected_names) > 1:
        names = set(state.selected_names)
        _record(state, f"move {len(names)} components")
        for ci, comp in enumerate(state.project.components):
            if getattr(comp, "name", None) in names:
                moves.move_component(state.project, ci, dx, dy)
                anchor = _current_anchor(comp)
                cname = getattr(comp, "name", None)
                if cname:
                    _sync_buffer_move(state, MoveOp(cname, anchor[0], anchor[1]))
        nav.rebuild(state.project)
        _refresh_tree_panel(state)
        return

    cur = nav.current
    comp = state.project.components[cur.component_index]
    name = getattr(comp, "name", None)
    _record(state, "move")
    if cur.is_node and cur.movable:
        moves.move_node(state.project, cur.component_index, cur.point_index, dx, dy)
    else:
        # Header row, single-anchor, or read-only multinode pin → move body.
        moves.move_component(state.project, cur.component_index, dx, dy)
    # Mirror the change in the working buffer.
    if name:
        if cur.is_node and cur.movable and hasattr(comp, "points"):
            cps = control_points_of(comp, cur.component_index)
            pt = next(p for p in cps if p.point_index == cur.point_index)
            _sync_buffer_move(state, MoveOp(name, pt.x, pt.y, point_index=cur.point_index))
        elif cur.is_node and cur.movable and hasattr(comp, "x2"):
            cps = control_points_of(comp, cur.component_index)
            pt = next(p for p in cps if p.point_index == cur.point_index)
            _sync_buffer_move(state, MoveOp(name, pt.x, pt.y, second_point=(cur.point_index == 1)))
        else:
            anchor = _current_anchor(comp)
            _sync_buffer_move(state, MoveOp(name, anchor[0], anchor[1]))
    nav.rebuild(state.project)
    _refresh_tree_panel(state)


def _tree_rotate(state: _ViewerState, clockwise: bool) -> None:
    """Rotate the focused component 90°. If a multi-selection (N>1) is
    active, every selected component spins about its own anchor.
    """
    from . import moves

    nav = state.nav
    if nav is None or nav.current is None:
        return

    # Bulk path: rotate each selected component independently.
    if len(state.selected_names) > 1:
        names = set(state.selected_names)
        _record(state, f"rotate {len(names)} components")
        for ci, comp in enumerate(state.project.components):
            if getattr(comp, "name", None) in names:
                moves.rotate_component(state.project, ci, clockwise=clockwise)
                _sync_buffer_rotate(state, state.project.components[ci])
        nav.rebuild(state.project)
        _refresh_tree_panel(state)
        return

    ci = nav.current.component_index
    _record(state, "rotate")
    moves.rotate_component(state.project, ci, clockwise=clockwise)
    # Mirror the rotation in the working buffer (orientation= keyword for
    # parts with an orientation enum; raw-coord replacement otherwise).
    _sync_buffer_rotate(state, state.project.components[ci])
    nav.rebuild(state.project)
    _refresh_tree_panel(state)


def _tree_duplicate(state: _ViewerState) -> None:
    """Clone the focused component to the right, with an incremented name.

    Uses the same value/orientation/color fields as the original; just
    shifts coords by 0.3 in to the right. Mirrors to the working buffer.

    If a multi-selection (N>1) is active, every selected component is
    cloned in one snapshot. The new selection becomes the set of clones
    so the user can immediately reposition them as a group.
    """
    from . import tree_editor

    nav = state.nav
    if nav is None or nav.current is None:
        return

    # Bulk path: duplicate every selected component.
    if len(state.selected_names) > 1:
        names = set(state.selected_names)
        originals = [c for c in state.project.components
                     if getattr(c, "name", None) in names]
        _record(state, f"duplicate {len(originals)} components")
        existing = {getattr(c, "name", None) for c in state.project.components}
        existing.discard(None)
        clone_names: set[str] = set()
        for original in originals:
            new_name = tree_editor.increment_name(
                existing, getattr(original, "name", "X")
            )
            existing.add(new_name)
            clone = tree_editor.duplicate_component(
                original, new_name, dx=0.3, dy=0.0
            )
            state.project.add(clone)
            _sync_buffer_add(state, clone)
            clone_names.add(new_name)
        # Hand the user the clones as the new active selection.
        state.selected_names = clone_names
        state.selected_name = next(iter(clone_names), None)
        nav.rebuild(state.project)
        _refresh_tree_panel(state)
        if state.canvas is not None:
            state.canvas.queue_draw()
        return

    ci = nav.current.component_index
    if not (0 <= ci < len(state.project.components)):
        return
    original = state.project.components[ci]
    existing = {getattr(c, "name", None) for c in state.project.components}
    existing.discard(None)
    new_name = tree_editor.increment_name(existing, getattr(original, "name", "X"))
    clone = tree_editor.duplicate_component(original, new_name, dx=0.3, dy=0.0)
    _record(state, f"duplicate {original.__class__.__name__}")
    state.project.add(clone)
    _sync_buffer_add(state, clone)
    if state.nav is not None:
        state.nav.rebuild(state.project)
        state.nav.focus_node(len(state.project.components) - 1, None)
    _refresh_tree_panel(state)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _open_edit_value_dialog(state: _ViewerState) -> None:
    """Inline editor for the focused component's primary value/text field.

    Opens a small popup with a single text entry pre-filled with the
    current value; Enter applies, Escape cancels. The edit flows through
    a KeywordOp so the working buffer stays in sync.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
    from . import tree_editor
    from .edit import KeywordOp

    nav = state.nav
    if nav is None or nav.current is None:
        _info_dialog(state.window, "Nothing to edit",
                     "Focus a component first (Tab or click).")
        return
    ci = nav.current.component_index
    comp = state.project.components[ci]
    field = tree_editor.primary_value_field(comp)
    if field is None:
        _info_dialog(state.window, "No editable value",
                     f"{type(comp).__name__} has no value/text/resistance "
                     "field to edit.")
        return
    name = getattr(comp, "name", None)
    if not name:
        _info_dialog(state.window, "No name",
                     "This component has no name= argument, so the buffer "
                     "can't locate it for an edit.")
        return

    # Bulk: when >1 selected, find every selected component that has
    # the same field and prep the dialog to apply to all of them.
    bulk_targets: list = []
    if len(state.selected_names) > 1:
        for c in state.project.components:
            cname = getattr(c, "name", None)
            if cname in state.selected_names and hasattr(c, field):
                bulk_targets.append(c)

    win = Gtk.Window()
    if bulk_targets and len(bulk_targets) > 1:
        win.set_title(f"Edit .{field} on {len(bulk_targets)} components")
    else:
        win.set_title(f"Edit {name}.{field}")
    win.set_default_size(360, 130)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(14); box.set_margin_bottom(14)
    box.set_margin_start(14); box.set_margin_end(14)

    if bulk_targets and len(bulk_targets) > 1:
        label = Gtk.Label(label=f"set .{field} on {len(bulk_targets)} components =")
    else:
        label = Gtk.Label(label=f"{name}.{field} =")
    label.set_xalign(0.0)
    box.append(label)

    entry = Gtk.Entry()
    entry.set_text(str(getattr(comp, field, "")))
    box.append(entry)

    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    btn_box.set_halign(Gtk.Align.END)
    cancel_btn = Gtk.Button(label="Cancel  (Esc)")
    apply_btn = Gtk.Button(label="Apply  (Enter)")
    apply_btn.add_css_class("suggested-action")

    def do_apply():
        new_value = entry.get_text()
        # Bulk path: apply to every selected component that has `field`.
        if bulk_targets and len(bulk_targets) > 1:
            _record(state, f"edit .{field} on {len(bulk_targets)} components")
            failed: list[str] = []
            for target in bulk_targets:
                tname = getattr(target, "name", None)
                if not tname:
                    continue
                try:
                    setattr(target, field, new_value)
                except (ValueError, TypeError) as exc:
                    failed.append(f"{tname}: {exc}")
                    continue
                if state.buffer is not None:
                    try:
                        proposal = state.buffer.propose(
                            keyword_ops=[KeywordOp(tname, field, new_value)]
                        )
                        if proposal is not None:
                            state.buffer.apply(proposal)
                    except (LookupError, NotImplementedError) as exc:
                        state.error_msg = f"buffer sync ({tname}): {exc}"
            if failed:
                _info_dialog(state.window, "Some values rejected",
                             "\n".join(failed))
            if state.canvas is not None:
                state.canvas.queue_draw()
            _refresh_tree_panel(state)
            win.close()
            return

        old_value = getattr(comp, field, None)
        if new_value == str(old_value):
            win.close()
            return
        _record(state, f"edit {name}.{field}")
        try:
            setattr(comp, field, new_value)
        except (ValueError, TypeError) as exc:
            _info_dialog(state.window, "Invalid value", str(exc))
            return
        # Buffer-sync via KeywordOp.
        if state.buffer is not None:
            try:
                proposal = state.buffer.propose(
                    keyword_ops=[KeywordOp(name, field, new_value)]
                )
                if proposal is not None:
                    state.buffer.apply(proposal)
            except (LookupError, NotImplementedError) as exc:
                state.error_msg = f"buffer sync: {exc}"
        if state.canvas is not None:
            state.canvas.queue_draw()
        _refresh_tree_panel(state)
        win.close()

    cancel_btn.connect("clicked", lambda _b: win.close())
    apply_btn.connect("clicked", lambda _b: do_apply())
    btn_box.append(cancel_btn)
    btn_box.append(apply_btn)
    box.append(btn_box)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            do_apply(); return True
        if keyval == Gdk.KEY_Escape:
            win.close(); return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.set_default_widget(apply_btn)
    win.present()
    entry.grab_focus()
    entry.select_region(0, -1)  # select-all so user can just type


def _tree_delete(state: _ViewerState) -> None:
    """Remove the focused component (dd). If a multi-selection is
    active (N>1), removes every selected component in one snapshot.
    """
    nav = state.nav
    if nav is None or nav.current is None:
        return

    # Bulk path: multi-select takes precedence over the tree cursor so
    # the user's visible selection is what gets deleted.
    if len(state.selected_names) > 1:
        names = set(state.selected_names)
        _record(state, f"delete {len(names)} components")
        # Walk indices in reverse so deletions don't shift remaining ones.
        for ci in reversed(range(len(state.project.components))):
            comp = state.project.components[ci]
            cname = getattr(comp, "name", None)
            if cname in names:
                del state.project.components[ci]
                _sync_buffer_delete(state, cname)
        state.selected_names.clear()
        state.selected_name = None
        nav.rebuild(state.project)
        nav.clamp_cursor()
        _refresh_tree_panel(state)
        if state.canvas is not None:
            state.canvas.queue_draw()
        return

    ci = nav.current.component_index
    if not (0 <= ci < len(state.project.components)):
        return
    comp = state.project.components[ci]
    name = getattr(comp, "name", None)
    _record(state, "delete")
    del state.project.components[ci]
    # Mirror the delete in the working buffer (removes the `p.add(...)` line).
    _sync_buffer_delete(state, name)
    if name is not None:
        state.selected_names.discard(name)
        if state.selected_name == name:
            state.selected_name = None
    nav.rebuild(state.project)
    nav.clamp_cursor()
    _refresh_tree_panel(state)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _tree_undo(state: _ViewerState) -> None:
    if state.history is None or not state.history.can_undo():
        return
    state.history.undo()
    if state.nav is not None:
        state.nav.rebuild(state.project)
        state.nav.clamp_cursor()
    _refresh_tree_panel(state)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _tree_redo(state: _ViewerState) -> None:
    if state.history is None or not state.history.can_redo():
        return
    state.history.redo()
    if state.nav is not None:
        state.nav.rebuild(state.project)
        state.nav.clamp_cursor()
    _refresh_tree_panel(state)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _tree_commit(state: _ViewerState) -> None:
    """Commit the focused component's position + any pending in-memory adds.

    Pending adds are components whose name isn't yet present in the source
    file (typically added via `a`). They are bundled into the same write so
    a subsequent watcher-triggered reload doesn't clobber them.
    """
    nav = state.nav
    if nav is None or nav.current is None:
        return
    cur = nav.current
    comp = state.project.components[cur.component_index]
    name = getattr(comp, "name", None)
    if not name or state.watch_path is None or state.watch_path.suffix.lower() != ".py":
        _info_dialog(
            state.window, "Can't commit",
            "Committing edits to source needs a .py layout with named "
            "components. The move is applied in-memory only.",
        )
        return
    from .edit import (
        propose_changes, MoveOp, propose_add, locate_component,
    )
    from . import graph as _g

    # Identify pending in-memory adds: components whose names aren't in source.
    pending_adds = _pending_in_memory_components(state)
    focused_is_pending = comp in pending_adds

    # Build the move op for the focused component, unless it's itself pending
    # (in which case it just becomes one of the adds).
    move_ops: list = []
    if not focused_is_pending:
        if cur.is_node and cur.movable and hasattr(comp, "points"):
            move_ops.append(MoveOp(name, cur.x, cur.y, point_index=cur.point_index))
        elif cur.is_node and cur.movable and hasattr(comp, "x2"):
            cps = _g.control_points_of(comp, cur.component_index)
            pt = next(p for p in cps if p.point_index == cur.point_index)
            move_ops.append(MoveOp(name, pt.x, pt.y, second_point=(cur.point_index == 1)))
        else:
            anchor = _current_anchor(comp)
            move_ops.append(MoveOp(name, anchor[0], anchor[1]))

    try:
        proposal = propose_changes(
            state.watch_path, moves=move_ops, adds=pending_adds,
        )
    except LookupError as exc:
        _info_dialog(state.window, "Can't auto-apply", str(exc))
        return
    except NotImplementedError:
        # A move op hit positional coords or similar — fall back to the
        # read-only locate dialog for the focused component.
        try:
            loc = locate_component(state.watch_path, name)
        except LookupError as exc:
            _info_dialog(state.window, "Can't auto-apply", str(exc))
            return
        _locate_dialog(state, loc, _current_anchor(comp))
        return
    _apply_dialog(state, proposal)


def _pending_in_memory_components(state: _ViewerState) -> list:
    """Return components present in the live project but absent from source.

    A component is considered pending if its ``name`` doesn't match any
    ``<Class>(name='X', ...)`` call in the source file. Used by
    _tree_commit to bundle uncommitted adds with a regular move.
    """
    if state.watch_path is None or state.watch_path.suffix.lower() != ".py":
        return []
    import ast as _ast
    from .edit import _find_name_arg

    try:
        text = state.watch_path.read_text(encoding="utf-8")
        tree = _ast.parse(text)
    except (OSError, SyntaxError):
        return []
    source_names: set[str] = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            n = _find_name_arg(node)
            if n:
                source_names.add(n)
    return [
        c for c in state.project.components
        if getattr(c, "name", None) and getattr(c, "name") not in source_names
    ]


def _format_diff(hunk: list[tuple[int, str, str]]) -> str:
    """Render a (line_no, old, new) hunk as a line-numbered unified diff."""
    out = []
    width = max((len(str(n)) for n, _o, _n in hunk), default=1)
    for line_no, old, new in hunk:
        gutter = str(line_no).rjust(width)
        if old == new:
            out.append(f"  {gutter} │ {old}")
        else:
            out.append(f"- {gutter} │ {old}")
            out.append(f"+ {gutter} │ {new}")
    return "\n".join(out)


def _format_context(context: list[tuple[int, str]], focus_line: int) -> str:
    """Render a (line_no, source) window with a ► marker on the focus line."""
    out = []
    width = max((len(str(n)) for n, _ in context), default=1)
    for line_no, src in context:
        marker = "►" if line_no == focus_line else " "
        gutter = str(line_no).rjust(width)
        out.append(f"{marker} {gutter} │ {src}")
    return "\n".join(out)


def _make_motion_handler(state: _ViewerState):
    def on_motion(_ctl, x, y):
        # Convert screen coords (canvas-local) → project inches.
        cx = (x - state.pan_x) / state.zoom
        cy = (y - state.pan_y) / state.zoom
        ix = cx / cairo_render.PX_PER_INCH
        iy = cy / cairo_render.PX_PER_INCH
        state.cursor_in = (ix, iy)
        _refresh_status(state)
    return on_motion


def _clear_cursor(state: _ViewerState) -> None:
    state.cursor_in = None
    _refresh_status(state)


def _make_scroll_handler(state: _ViewerState, canvas):
    def on_scroll(controller, dx, dy):
        # Zoom about the canvas centre. Negative dy = scroll up = zoom in.
        old = state.zoom
        factor = 0.9 if dy > 0 else 1.1
        state.zoom = max(0.1, min(10.0, old * factor))
        canvas.queue_draw()
        _refresh_status(state)
        return True
    return on_scroll


def _make_key_handler(state: _ViewerState, canvas, win):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk

    def on_key(controller, keyval, keycode, modifiers):
        ctrl = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(modifiers & Gdk.ModifierType.SHIFT_MASK)

        # T toggles tree-editor mode (works in or out of it).
        if keyval in (Gdk.KEY_t, Gdk.KEY_T):
            if state.tree_mode:
                _exit_tree_mode(state)
            else:
                _enter_tree_mode(state)
            return True

        # "?" opens the keyboard-shortcut help (which-key style).
        if keyval == Gdk.KEY_question:
            _open_help_dialog(state)
            return True

        # In tree mode, navigation/move/rotate/commit keys take over.
        if state.tree_mode and state.nav is not None:
            if _handle_tree_key(state, canvas, keyval, ctrl, shift):
                return True

        if keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_Escape):
            if state.tree_mode:
                _exit_tree_mode(state)
                return True
            win.close()
            return True
        if keyval in (Gdk.KEY_r, Gdk.KEY_R):
            _reload(state)
            canvas.queue_draw()
            return True
        if keyval in (Gdk.KEY_0,):
            _fit_to_page(state)
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            _zoom_by(state, 1.2)
            return True
        if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            _zoom_by(state, 1 / 1.2)
            return True
        return False
    return on_key


def _handle_tree_key(state: _ViewerState, canvas, keyval, ctrl: bool, shift: bool) -> bool:
    """Handle a key while in tree-editor mode. Returns True if consumed."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk

    nav = state.nav
    grid = state.project.grid_inches or 0.1
    step = grid if not shift else grid / 10.0  # Shift = finer

    # 'D' (uppercase, Shift+d) — duplicate the focused component. Not a chord.
    if keyval == Gdk.KEY_D:
        state.pending_d = False  # cancel any half-typed 'dd'
        _tree_duplicate(state)
        return True
    # 'dd' chord to delete the focused component. First 'd' arms it; a second
    # 'd' deletes; any other key cancels the pending state.
    if keyval == Gdk.KEY_d:
        if state.pending_d:
            state.pending_d = False
            _tree_delete(state)
        else:
            state.pending_d = True
            _refresh_status(state)
        return True
    # Any non-'d' key cancels a pending delete chord.
    if state.pending_d:
        state.pending_d = False
        _refresh_status(state)

    # 'u' undo (also Ctrl+Z). 'U' (shift+u) redo (also Ctrl+Y / Ctrl+Shift+Z).
    if keyval == Gdk.KEY_U or (
        ctrl and (
            keyval in (Gdk.KEY_y, Gdk.KEY_Y) or
            (shift and keyval in (Gdk.KEY_z, Gdk.KEY_Z))
        )
    ):
        _tree_redo(state)
        return True
    if keyval == Gdk.KEY_u or (
        ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z)
    ):
        _tree_undo(state)
        return True

    _DIRS = {
        Gdk.KEY_Left: "left", Gdk.KEY_Right: "right",
        Gdk.KEY_Up: "up", Gdk.KEY_Down: "down",
    }

    # Ctrl+arrow = literal nudge of the focused component/node by a grid step.
    if ctrl and keyval in _DIRS:
        direction = _DIRS[keyval]
        dx = -step if direction == "left" else step if direction == "right" else 0.0
        dy = -step if direction == "up" else step if direction == "down" else 0.0
        _tree_move(state, dx, dy)
        return True

    # Plain arrow = move the focused node by one board hole (if it's on a
    # perf/stripboard). Off-board, fall back to a grid-step nudge so arrows
    # still do something useful everywhere.
    if not ctrl and keyval in _DIRS:
        _tree_hole_nudge(state, _DIRS[keyval])
        return True

    # Tab / Shift-Tab: at component level, move between components; at node
    # level, walk the focused component's nodes. (GTK's own Tab focus
    # traversal is bypassed by attaching this controller in the CAPTURE phase.)
    is_tab = keyval == Gdk.KEY_Tab
    is_backtab = keyval in (Gdk.KEY_ISO_Left_Tab,) or (keyval == Gdk.KEY_Tab and shift)
    if is_tab or is_backtab:
        backward = is_backtab or shift
        if nav.node_level:
            nav.prev_node() if backward else nav.next_node()
        else:
            nav.prev_component() if backward else nav.next_component()
        _refresh_tree_panel(state)
        return True

    # Space: drill into / out of the focused component's nodes.
    if keyval == Gdk.KEY_space:
        if nav.node_level:
            nav.exit_nodes()
        else:
            nav.enter_nodes()  # no-op for single-anchor / multi-node parts
        _refresh_tree_panel(state)
        return True

    # Page Up/Down: jump _PAGE_STEP components at a time in the side panel.
    if keyval == Gdk.KEY_Page_Down:
        nav.page_component(+_PAGE_STEP)
        _refresh_tree_panel(state)
        return True
    if keyval == Gdk.KEY_Page_Up:
        nav.page_component(-_PAGE_STEP)
        _refresh_tree_panel(state)
        return True

    # R / Shift+R rotate.
    if keyval in (Gdk.KEY_r, Gdk.KEY_R):
        _tree_rotate(state, clockwise=not shift)
        return True

    # "/" — fuzzy search to FOCUS a node (like Tab nav, but searchable).
    if keyval == Gdk.KEY_slash:
        _open_fuzzy_menu(state, mode="focus")
        return True

    # "g" — fuzzy search to SEND the focused node to a destination.
    if keyval in (Gdk.KEY_g, Gdk.KEY_G):
        _open_fuzzy_menu(state, mode="send")
        return True

    # "a" — add a new component (type picker, placed at cursor or focused).
    # Lowercase 'a' auto-wires the new component to the focused node when it
    # makes sense; uppercase 'A' (Shift) skips the auto-wire.
    if keyval in (Gdk.KEY_a, Gdk.KEY_A):
        autowire = not shift
        _open_add_menu(state, autowire=autowire)
        return True

    # "v" — edit the focused component's primary value/text field.
    if keyval in (Gdk.KEY_v, Gdk.KEY_V):
        _open_edit_value_dialog(state)
        return True

    # Enter: silent flush of the working buffer to disk. No dialog, no
    # confirmation — Enter is "write what I've been editing" (matches the
    # editor mental model where Enter just commits the current edit).
    if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
        if state.buffer is not None:
            _flush_buffer_silent(state)
        else:
            _tree_commit(state)
        return True

    # Ctrl+S: explicit save with the diff-on-save dialog (gated by the
    # show_save_dialog preference).
    if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
        if state.buffer is not None:
            _save_buffer(state)
        else:
            _tree_commit(state)
        return True

    return False


def _tree_hole_nudge(state: _ViewerState, direction: str) -> None:
    """Move the focused node by one board hole, or a grid step if off-board."""
    from . import moves, jump

    nav = state.nav
    if nav is None or nav.current is None:
        return
    cur = nav.current
    # Find the point's current position.
    from .graph import control_points_of

    comp = state.project.components[cur.component_index]
    if cur.is_node and cur.movable:
        cps = control_points_of(comp, cur.component_index)
        pt = next((p for p in cps if p.point_index == cur.point_index), None)
        pos = (pt.x, pt.y) if pt else None
    else:
        pos = _current_anchor(comp)

    delta = jump.hole_delta(state.project, pos[0], pos[1], direction) if pos else None
    if delta is None:
        grid = state.project.grid_inches or 0.1
        delta = (
            -grid if direction == "left" else grid if direction == "right" else 0.0,
            -grid if direction == "up" else grid if direction == "down" else 0.0,
        )
    _tree_move(state, delta[0], delta[1])


def _open_fuzzy_menu(state: _ViewerState, *, mode: str) -> None:
    """Open the fuzzy search popup.

    mode='focus' → selecting a target moves the tree cursor to it.
    mode='send'  → selecting a target snaps the focused node onto it.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib
    from . import jump, moves

    nav = state.nav
    if nav is None or nav.current is None:
        return

    if mode == "send":
        targets = jump.searchable_targets(
            state.project, exclude_component=nav.current.component_index
        )
        title = "Send focused node to…"
    else:
        targets = jump.searchable_targets(state.project)
        title = "Go to node…"
    if not targets:
        return

    win = Gtk.Window()
    win.set_title(title)
    win.set_default_size(420, 360)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_margin_top(10); box.set_margin_bottom(10)
    box.set_margin_start(10); box.set_margin_end(10)

    entry = Gtk.SearchEntry()
    entry.set_placeholder_text(title)
    box.append(entry)

    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    sw.set_child(listbox)
    box.append(sw)

    # Keep the current filtered ordering so Enter picks the top match.
    current: dict[str, list] = {"items": list(targets)}

    def populate(items):
        child = listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            listbox.remove(child)
            child = nxt
        for t in items:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=f"{t.label}   ({t.x:g}, {t.y:g})")
            lbl.set_xalign(0.0)
            row.set_child(lbl)
            listbox.append(row)
        first = listbox.get_row_at_index(0)
        if first is not None:
            listbox.select_row(first)

    populate(current["items"])

    def on_changed(_e):
        items = jump.fuzzy_filter(targets, entry.get_text())
        current["items"] = items
        populate(items)

    entry.connect("search-changed", on_changed)

    def choose(target):
        if target is None:
            win.close()
            return
        if mode == "focus":
            nav.focus_node(target.component_index, target.point_index)
            _refresh_tree_panel(state)
        else:  # send
            cur = nav.current
            comp = state.project.components[cur.component_index]
            if cur.is_node and cur.movable:
                moves.move_node_to(
                    state.project, cur.component_index, cur.point_index,
                    target.x, target.y,
                )
            else:
                # Move the whole body so its anchor lands on the target.
                anchor = _current_anchor(comp)
                moves.move_component(
                    state.project, cur.component_index,
                    target.x - anchor[0], target.y - anchor[1],
                )
            nav.rebuild(state.project)
            _refresh_tree_panel(state)
        win.close()

    def selected_target():
        row = listbox.get_selected_row()
        if row is None:
            return current["items"][0] if current["items"] else None
        idx = row.get_index()
        items = current["items"]
        return items[idx] if 0 <= idx < len(items) else None

    listbox.connect("row-activated", lambda _lb, _row: choose(selected_target()))

    # CAPTURE phase so Enter/Escape/Up/Down reach us before the focused
    # SearchEntry consumes them.
    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            choose(selected_target())
            return True
        if keyval == Gdk.KEY_Down:
            _move_list_selection(listbox, +1)
            return True
        if keyval == Gdk.KEY_Up:
            _move_list_selection(listbox, -1)
            return True
        if keyval == Gdk.KEY_Page_Down:
            _move_list_selection(listbox, +_PAGE_STEP)
            return True
        if keyval == Gdk.KEY_Page_Up:
            _move_list_selection(listbox, -_PAGE_STEP)
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    win.set_child(box)
    win.present()
    entry.grab_focus()


_PAGE_STEP = 10  # rows per Page Up/Down keystroke (fuzzy menus + tree panel)


def _move_list_selection(listbox, delta: int) -> None:
    """Move the ListBox selection by ``delta`` rows and keep it visible.

    Selecting a row doesn't scroll the enclosing ScrolledWindow on its own,
    so a row past the viewport stays off-screen. We bring it into view by
    nudging the vadjustment, *without* grabbing focus (which would steal it
    from the SearchEntry mid-typing).
    """
    row = listbox.get_selected_row()
    idx = row.get_index() if row is not None else -1
    n_rows = 0
    while listbox.get_row_at_index(n_rows) is not None:
        n_rows += 1
    new_idx = max(0, min(n_rows - 1, idx + delta))
    nxt = listbox.get_row_at_index(new_idx)
    if nxt is None:
        return
    listbox.select_row(nxt)
    _scroll_into_view(listbox, nxt)


def _scroll_into_view(listbox, row) -> None:
    """Scroll the row's containing ScrolledWindow so ``row`` is visible.

    Walks up from the listbox to find the ScrolledWindow ancestor, then
    adjusts its vertical adjustment to expose the row. Rows are often
    not yet allocated on the first synchronous call (we just cleared and
    repopulated the listbox); a short retry chain via GLib idle + a few
    timeouts is reliable. Without focus-grabbing, so the SearchEntry in
    fuzzy menus doesn't lose its caret.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib

    parent = listbox.get_parent()
    sw = None
    while parent is not None:
        if isinstance(parent, Gtk.ScrolledWindow):
            sw = parent
            break
        parent = parent.get_parent()
    if sw is None:
        return

    attempts = {"n": 0}

    def do_scroll():
        adj = sw.get_vadjustment()
        if adj is None:
            return False  # nothing we can do
        row_alloc = row.get_allocation()
        if row_alloc.height == 0:
            # Not allocated yet; retry up to ~10 frames (~160 ms).
            attempts["n"] += 1
            if attempts["n"] >= 10:
                return False
            return True
        row_top = row_alloc.y
        row_bottom = row_top + row_alloc.height
        page = adj.get_page_size()
        value = adj.get_value()
        upper = adj.get_upper()
        if page <= 0 or upper <= 0:
            attempts["n"] += 1
            if attempts["n"] >= 10:
                return False
            return True
        if row_top < value:
            adj.set_value(row_top)
        elif row_bottom > value + page:
            adj.set_value(min(upper - page, row_bottom - page))
        return False  # done

    # Try synchronously first; if the row isn't allocated yet, retry on
    # idle, and as a belt-and-braces fallback on a short timeout chain.
    if do_scroll():
        GLib.idle_add(do_scroll)
        GLib.timeout_add(16, do_scroll)
        GLib.timeout_add(64, do_scroll)


def _focused_pin_position(state: _ViewerState) -> tuple[float, float] | None:
    """Where would an auto-wire start? Position of the focused node, or None
    if the cursor isn't sitting on a wire-able point.

    Wire-able means: a single-anchor component, a two-pin endpoint when
    drilled into nodes, or a points-list / multi-node pin. A component
    *header* on a multi-node body returns the anchor (so wiring from "VR1"
    starts from its center) — usable but less precise than focusing a
    specific lug.
    """
    nav = state.nav
    if nav is None or nav.current is None:
        return None
    cur = nav.current
    comp = state.project.components[cur.component_index]
    if cur.is_node and cur.x is not None and cur.y is not None:
        return (float(cur.x), float(cur.y))
    # Header row on a single-anchor component: use its position.
    if hasattr(comp, "x") and hasattr(comp, "y") and not hasattr(comp, "x1"):
        return (float(comp.x), float(comp.y))
    return None


def _create_wire(state: _ViewerState, src: tuple[float, float],
                 dst: tuple[float, float]) -> None:
    """Add a HookupWire from src to dst, syncing the buffer."""
    from . import tree_editor

    name = _auto_name(state, "HookupWire")
    wire = tree_editor.make_wire(name, src, dst)
    _record(state, "auto-wire")
    state.project.add(wire)
    _sync_buffer_add(state, wire)
    if state.nav is not None:
        state.nav.rebuild(state.project)
    _refresh_tree_panel(state)
    if state.canvas is not None:
        state.canvas.queue_draw()


def _autowire_after_add(state: _ViewerState,
                        source_pin: tuple[float, float], new_comp) -> None:
    """Hook up the freshly-added component to the source pin.

    Decides per pin count:
      - 0 pins (shouldn't happen for any add-able type): no-op.
      - 1 pin: wire immediately.
      - >1 pins: open the pin-picker fuzzy menu.
    """
    from . import tree_editor

    pins = tree_editor.addable_pins(new_comp)
    if not pins:
        return
    if len(pins) == 1:
        _create_wire(state, source_pin, (pins[0][2], pins[0][3]))
        return
    _open_pin_picker(state, source_pin, new_comp, pins)


def _open_pin_picker(state: _ViewerState,
                     source_pin: tuple[float, float], new_comp,
                     pins: list[tuple[int, str, float, float]]) -> None:
    """Fuzzy menu to pick which pin of ``new_comp`` to wire to."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk

    name = getattr(new_comp, "name", type(new_comp).__name__)

    win = Gtk.Window()
    win.set_title(f"Wire to {name}…")
    win.set_default_size(420, 360)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_margin_top(10); box.set_margin_bottom(10)
    box.set_margin_start(10); box.set_margin_end(10)
    entry = Gtk.SearchEntry()
    entry.set_placeholder_text(f"Pick a pin on {name}…")
    box.append(entry)
    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    sw.set_child(listbox)
    box.append(sw)

    # Each item carries its (point_index, label, x, y) tuple.
    items_state: dict[str, list[tuple[int, str, float, float]]] = {"items": list(pins)}

    def populate(items):
        child = listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            listbox.remove(child)
            child = nxt
        for pi, lbl, x, y in items:
            row = Gtk.ListBoxRow()
            l = Gtk.Label(label=f"{lbl}   ({x:g}, {y:g})")
            l.set_xalign(0.0)
            row.set_child(l)
            listbox.append(row)
        first = listbox.get_row_at_index(0)
        if first is not None:
            listbox.select_row(first)

    populate(items_state["items"])

    def filter_pins(q):
        q = q.lower().replace(" ", "")
        if not q:
            return list(pins)
        out = []
        for item in pins:
            hay = f"{name} {item[1]}".lower().replace(" ", "")
            qi = 0
            for ch in hay:
                if qi < len(q) and ch == q[qi]:
                    qi += 1
            if qi == len(q):
                out.append(item)
        return out

    def on_changed(_e):
        items = filter_pins(entry.get_text())
        items_state["items"] = items
        populate(items)
    entry.connect("search-changed", on_changed)

    def choose():
        items = items_state["items"]
        row = listbox.get_selected_row()
        idx = row.get_index() if row is not None else 0
        if not items or not (0 <= idx < len(items)):
            win.close()
            return
        _pi, _lbl, x, y = items[idx]
        win.close()
        _create_wire(state, source_pin, (x, y))

    listbox.connect("row-activated", lambda _lb, _row: choose())

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            choose()
            return True
        if keyval == Gdk.KEY_Down:
            _move_list_selection(listbox, +1); return True
        if keyval == Gdk.KEY_Up:
            _move_list_selection(listbox, -1); return True
        if keyval == Gdk.KEY_Page_Down:
            _move_list_selection(listbox, +_PAGE_STEP); return True
        if keyval == Gdk.KEY_Page_Up:
            _move_list_selection(listbox, -_PAGE_STEP); return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.present()
    entry.grab_focus()


def _auto_name(state: _ViewerState, type_name: str) -> str:
    """Generate a unique name like 'Resistor1' for a new component."""
    existing = {getattr(c, "name", None) for c in state.project.components}
    i = 1
    while f"{type_name}{i}" in existing:
        i += 1
    return f"{type_name}{i}"


def _open_add_menu(state: _ViewerState, *, autowire: bool = False) -> None:
    """Fuzzy picker of component types; creates one near the focused component.

    When ``autowire`` is True and the cursor is on a wire-able node (single
    anchor or a movable endpoint), after the new component is created we
    add a HookupWire connecting the focused node to one of the new
    component's pins. Multi-pin parts get a pin-picker dialog.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
    from . import tree_editor

    # Snapshot the source node (where the wire would start) at menu-open
    # time — once `a` selection lands, the cursor will have moved to the
    # newly-added component.
    source_pin = _focused_pin_position(state) if autowire else None

    type_names = tree_editor.addable_component_types()

    win = Gtk.Window()
    win.set_title("Add component…")
    win.set_default_size(420, 400)
    if state.window is not None:
        win.set_transient_for(state.window)
        win.set_modal(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_margin_top(10); box.set_margin_bottom(10)
    box.set_margin_start(10); box.set_margin_end(10)
    entry = Gtk.SearchEntry()
    entry.set_placeholder_text("Add component… (type to filter)")
    box.append(entry)
    sw = Gtk.ScrolledWindow()
    sw.set_vexpand(True)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    sw.set_child(listbox)
    box.append(sw)

    state_items: dict[str, list[str]] = {"items": list(type_names)}

    def _simple_filter(names, query):
        q = query.lower().replace(" ", "")
        if not q:
            return list(names)
        out = []
        for n in names:
            hay = n.lower()
            qi = 0
            for ch in hay:
                if qi < len(q) and ch == q[qi]:
                    qi += 1
            if qi == len(q):
                out.append(n)
        return out

    def populate(items):
        child = listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            listbox.remove(child)
            child = nxt
        for n in items:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=n)
            lbl.set_xalign(0.0)
            row.set_child(lbl)
            listbox.append(row)
        first = listbox.get_row_at_index(0)
        if first is not None:
            listbox.select_row(first)

    populate(state_items["items"])

    def on_changed(_e):
        items = _simple_filter(type_names, entry.get_text())
        state_items["items"] = items
        populate(items)

    entry.connect("search-changed", on_changed)

    def placement() -> tuple[float, float]:
        # Prefer the explicit click position (right-click Add Here) or the
        # current cursor — most natural placement target.
        target = state.next_add_at or state.cursor_in
        if target is not None:
            grid = state.project.grid_inches or 0.1
            return (round(round(target[0] / grid) * grid, 4),
                    round(round(target[1] / grid) * grid, 4))
        # Fall back to "near focused component".
        nav = state.nav
        if nav is not None and nav.current is not None:
            comp = state.project.components[nav.current.component_index]
            ax, ay = _current_anchor(comp)
            return (round(ax + 0.5, 4), round(ay + 0.5, 4))
        return (1.0, 1.0)

    def choose():
        items = state_items["items"]
        row = listbox.get_selected_row()
        idx = row.get_index() if row is not None else 0
        if not items or not (0 <= idx < len(items)):
            win.close()
            return
        type_name = items[idx]
        x, y = placement()
        name = _auto_name(state, type_name)
        try:
            comp = tree_editor.make_default_component(type_name, name, x, y)
        except (ValueError, TypeError) as exc:
            _info_dialog(state.window, "Can't add", str(exc))
            win.close()
            return
        _record(state, f"add {type_name}")
        state.project.add(comp)
        # Consume any one-shot placement target.
        state.next_add_at = None
        # Mirror the add in the working buffer.
        _sync_buffer_add(state, comp)
        # Refresh the tree + focus the new component.
        if state.nav is not None:
            state.nav.rebuild(state.project)
            state.nav.focus_node(len(state.project.components) - 1, None)
        _refresh_tree_panel(state)
        if state.canvas is not None:
            state.canvas.queue_draw()
        win.close()
        # Auto-wire: if we captured a source pin at menu-open time and the
        # user didn't suppress with Shift, run the wire flow now. The wire
        # flow either fires immediately (1 pin) or opens a pin-picker.
        if source_pin is not None:
            _autowire_after_add(state, source_pin, comp)

    listbox.connect("row-activated", lambda _lb, _row: choose())

    # CAPTURE phase so the focused SearchEntry doesn't swallow Enter/Escape.
    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def on_key(_ctl, keyval, _code, _mods):
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            choose()
            return True
        if keyval == Gdk.KEY_Down:
            _move_list_selection(listbox, +1)
            return True
        if keyval == Gdk.KEY_Up:
            _move_list_selection(listbox, -1)
            return True
        if keyval == Gdk.KEY_Page_Down:
            _move_list_selection(listbox, +_PAGE_STEP)
            return True
        if keyval == Gdk.KEY_Page_Up:
            _move_list_selection(listbox, -_PAGE_STEP)
            return True
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)
    win.set_child(box)
    win.present()
    entry.grab_focus()


def _make_poller(state: _ViewerState):
    def poll():
        if state.watch_path is None or state.builder is None:
            return False  # stop polling
        try:
            mtime = state.watch_path.stat().st_mtime
        except OSError:
            return True
        if mtime == state.last_mtime:
            return True

        # External change. If our buffer is dirty, refuse to clobber it —
        # surface a conflict in the status bar and update the mtime watermark
        # so we don't keep re-prompting on the same external mtime. The
        # buffer's disk_text is intentionally NOT updated; that lets the
        # save-diff dialog show a clear three-way picture if the user picks
        # Save (their buffer overwrites the external change).
        if state.buffer is not None and state.buffer.is_dirty:
            state.error_msg = (
                f"{state.watch_path.name} changed on disk while you have "
                "unsaved edits — Ctrl+S will overwrite, or close without "
                "saving to discard"
            )
            state.last_mtime = mtime
            _refresh_status(state)
            return True

        state.last_mtime = mtime
        _reload(state)
        # Re-sync the buffer to the new disk state so subsequent edits
        # build on what's actually on disk.
        if state.buffer is not None:
            try:
                state.buffer.discard()  # re-reads from disk
            except OSError:
                pass
        if state.canvas is not None:
            state.canvas.queue_draw()
        return True
    return poll


def _reload(state: _ViewerState) -> None:
    if state.builder is None:
        return
    try:
        state.project = state.builder()
        state.error_msg = None
    except Exception as exc:
        state.error_msg = f"{type(exc).__name__}: {exc}"
    # Re-size the canvas content area if the project dimensions changed.
    if state.canvas is not None:
        _size_canvas_to_project(state.project, state.canvas)
    _refresh_status(state)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="pydiylc-view",
        description="GTK4 viewer for pydiylc layouts (Python or JSON sources).",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to a .py file that builds a Project, or a .json layout file.",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Disable auto-reload on file change.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Just verify GTK is importable and exit (for CI / install verification).",
    )
    args = parser.parse_args(argv)

    if args.check:
        ok = has_gtk()
        print("GTK 4 available" if ok else "GTK 4 NOT available")
        return 0 if ok else 1

    if not args.path:
        parser.print_help()
        return 2

    try:
        project, builder = load(args.path)
    except (FileNotFoundError, NotImplementedError, ValueError, RuntimeError) as exc:
        print(f"pydiylc-view: {exc}", file=sys.stderr)
        return 2

    show(
        project,
        title=f"pydiylc — {os.path.basename(args.path)}",
        builder=None if args.no_watch else builder,
        watch_path=None if args.no_watch else args.path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
