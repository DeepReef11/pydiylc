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
        status_lbl = Gtk.Label(label=_status_text(state))
        status_lbl.add_css_class("dim-label")
        header.pack_end(status_lbl)
        state.status_lbl = status_lbl

        # Main content: canvas in a scrolled window
        sw = Gtk.ScrolledWindow()
        sw.set_hexpand(True)
        sw.set_vexpand(True)

        canvas = Gtk.DrawingArea()
        canvas.set_draw_func(_make_draw_func(state))
        canvas.set_content_width(2200)
        canvas.set_content_height(1600)
        state.canvas = canvas

        # Mouse handlers
        click = Gtk.GestureClick()
        click.set_button(0)  # any
        click.connect("pressed", _make_click_handler(state, canvas))
        canvas.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", _make_drag_begin(state))
        drag.connect("drag-update", _make_drag_update(state, canvas))
        drag.connect("drag-end", _make_drag_end(state, canvas))
        canvas.add_controller(drag)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", _make_scroll_handler(state, canvas))
        canvas.add_controller(scroll)

        sw.set_child(canvas)

        # Side panel (tree editor) + canvas in a horizontal Paned. The panel
        # is built collapsed/hidden; pressing T toggles it.
        panel = _build_tree_panel(state)
        state.tree_panel = panel
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_start_child(panel)
        paned.set_end_child(sw)
        paned.set_position(260)
        paned.set_resize_start_child(False)
        state.paned = paned
        panel.set_visible(False)  # hidden until T
        win.set_child(paned)

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
        self.selected_name: str | None = None
        self.last_drag_pan: tuple[float, float] | None = None
        # Component-move state. When the user Ctrl+drags, this holds the
        # component being dragged plus its original anchor so we can compute
        # deltas live and propose the final move on drag-end.
        self.moving_component = None
        self.moving_orig_anchor: tuple[float, float] | None = None
        self.last_drag_delta: tuple[float, float] = (0.0, 0.0)
        # Tree-editor mode.
        self.tree_mode: bool = False
        self.nav = None  # tree_editor.NavState, lazily built
        self.history = None  # history.History, built on entering tree mode
        self.pending_d: bool = False  # first 'd' of a 'dd' delete chord
        # Filled in by show()
        self.canvas = None
        self.status_lbl = None
        self.window = None
        self.tree_panel = None
        self.paned = None
        self.tree_listbox = None
        self.error_msg: str | None = None


def _status_text(state: _ViewerState) -> str:
    n = len(state.project.components)
    title = state.project.title or "untitled"
    sel = f"  ·  sel: {state.selected_name}" if state.selected_name else ""
    err = f"  ·  ⚠ {state.error_msg}" if state.error_msg else ""
    chord = "  ·  d… (press d again to delete)" if state.pending_d else ""
    undo = ""
    if state.tree_mode and state.history is not None and state.history.can_undo():
        undo = f"  ·  undo×{state.history.depth()}"
    return f"{title}  ·  {n} components  ·  zoom {state.zoom:.2f}{sel}{undo}{chord}{err}"


def _refresh_status(state: _ViewerState) -> None:
    if state.status_lbl is not None:
        state.status_lbl.set_text(_status_text(state))


def _make_draw_func(state: _ViewerState):
    def draw(area, cr, width, height):
        # Background
        cr.set_source_rgb(0.97, 0.97, 0.97)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.save()
        cr.translate(state.pan_x, state.pan_y)
        cr.scale(state.zoom, state.zoom)
        cairo_render.draw_project(
            cr,
            state.project,
            scale=cairo_render.PX_PER_INCH,
            background=(1, 1, 1),
            show_grid=True,
            selected_name=state.selected_name,
        )
        cr.restore()
    return draw


def _project_xy_from_screen(state: _ViewerState, sx: float, sy: float) -> tuple[float, float]:
    """Inverse of the canvas transform — used for click hit-testing."""
    cx = (sx - state.pan_x) / state.zoom
    cy = (sy - state.pan_y) / state.zoom
    return cx, cy


def _make_click_handler(state: _ViewerState, canvas):
    def on_click(gesture, n_press, x, y):
        cx, cy = _project_xy_from_screen(state, x, y)
        hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
        if hit is not None:
            state.selected_name = getattr(hit, "name", None)
        else:
            state.selected_name = None
        canvas.queue_draw()
        _refresh_status(state)
    return on_click


def _make_drag_begin(state: _ViewerState):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk

    def on_begin(gesture, x, y):
        # Determine the mode based on whether Ctrl is held.
        device = gesture.get_device()
        seat = device.get_seat() if device else None
        ctrl_held = False
        if seat is not None:
            kbd = seat.get_keyboard()
            if kbd is not None:
                ctrl_held = bool(kbd.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK)

        # If Ctrl is held and a hit is under the cursor, enter move-component
        # mode. Otherwise plain pan.
        if ctrl_held:
            cx, cy = _project_xy_from_screen(state, x, y)
            hit = cairo_render.hit_test(state.project, cx, cy, cairo_render.PX_PER_INCH)
            if hit is not None:
                state.moving_component = hit
                state.moving_orig_anchor = _current_anchor(hit)
                state.last_drag_delta = (0.0, 0.0)
                state.selected_name = getattr(hit, "name", None)
                _refresh_status(state)
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
        if state.last_drag_pan is None:
            return
        state.pan_x = state.last_drag_pan[0] + dx
        state.pan_y = state.last_drag_pan[1] + dy
        canvas.queue_draw()
    return on_update


def _make_drag_end(state: _ViewerState, canvas):
    def on_end(gesture, dx, dy):
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

    # Enter = Apply, Escape = Cancel.
    key = Gtk.EventControllerKey()

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

    title = Gtk.Label(label="Components  (T to close)")
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
        label="Tab component · Space drill · arrows hole-move · Ctrl+arrows nudge\n"
              "R rotate · / focus · g send · a add · dd delete · u undo · Enter commit"
    )
    hint.add_css_class("dim-label")
    hint.set_wrap(True)
    box.append(hint)
    return box


def _enter_tree_mode(state: _ViewerState) -> None:
    from .tree_editor import build_tree, NavState
    from .history import History

    state.nav = NavState(build_tree(state.project))
    state.history = History(state.project)
    state.pending_d = False
    state.tree_mode = True
    if state.tree_panel is not None:
        state.tree_panel.set_visible(True)
    _refresh_tree_panel(state)


def _exit_tree_mode(state: _ViewerState) -> None:
    state.tree_mode = False
    if state.tree_panel is not None:
        state.tree_panel.set_visible(False)


def _refresh_tree_panel(state: _ViewerState) -> None:
    """Rebuild the listbox rows from nav state and sync canvas selection."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    lb = state.tree_listbox
    nav = state.nav
    if lb is None or nav is None:
        return
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
        if row.is_node and not row.movable:
            lbl.add_css_class("dim-label")
        lr = Gtk.ListBoxRow()
        lr.set_child(lbl)
        lb.append(lr)
        if i == nav.cursor:
            selected_row = lr
    if selected_row is not None:
        lb.select_row(selected_row)
    # Sync the canvas highlight to the focused component.
    cur = nav.current
    if cur is not None:
        comp = state.project.components[cur.component_index]
        state.selected_name = getattr(comp, "name", None)
        if state.canvas is not None:
            state.canvas.queue_draw()
    _refresh_status(state)


def _record(state: _ViewerState, label: str) -> None:
    if state.history is not None:
        state.history.record(label)


def _tree_move(state: _ViewerState, dx: float, dy: float) -> None:
    """Apply a literal nudge to the focused component or node."""
    from . import moves

    nav = state.nav
    if nav is None or nav.current is None:
        return
    cur = nav.current
    _record(state, "move")
    if cur.is_node and cur.movable:
        moves.move_node(state.project, cur.component_index, cur.point_index, dx, dy)
    else:
        # Header row, single-anchor, or read-only multinode pin → move body.
        moves.move_component(state.project, cur.component_index, dx, dy)
    nav.rebuild(state.project)
    _refresh_tree_panel(state)


def _tree_rotate(state: _ViewerState, clockwise: bool) -> None:
    from . import moves

    nav = state.nav
    if nav is None or nav.current is None:
        return
    _record(state, "rotate")
    moves.rotate_component(state.project, nav.current.component_index, clockwise=clockwise)
    nav.rebuild(state.project)
    _refresh_tree_panel(state)


def _tree_delete(state: _ViewerState) -> None:
    """Remove the focused component (dd). In-memory only."""
    nav = state.nav
    if nav is None or nav.current is None:
        return
    ci = nav.current.component_index
    if not (0 <= ci < len(state.project.components)):
        return
    _record(state, "delete")
    del state.project.components[ci]
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


def _tree_commit(state: _ViewerState) -> None:
    """Commit the focused component's current position to source via a dialog."""
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
    from .edit import propose_move, propose_point_move, propose_add, locate_component
    from . import graph as _g

    try:
        if cur.is_node and cur.movable and hasattr(comp, "points"):
            anchor = (cur.x, cur.y)
            proposal = propose_point_move(
                state.watch_path, name, cur.point_index, anchor[0], anchor[1]
            )
        elif cur.is_node and cur.movable and hasattr(comp, "x2"):
            cps = _g.control_points_of(comp, cur.component_index)
            pt = next(p for p in cps if p.point_index == cur.point_index)
            proposal = propose_move(
                state.watch_path, name, pt.x, pt.y,
                second_point=(cur.point_index == 1),
            )
        else:
            anchor = _current_anchor(comp)
            proposal = propose_move(state.watch_path, name, anchor[0], anchor[1])
    except LookupError:
        # Component isn't in the source — typically because it was just added
        # in-memory via `a`. Offer to insert a new line.
        try:
            proposal = propose_add(state.watch_path, comp)
        except NotImplementedError as exc:
            _info_dialog(state.window, "Can't auto-insert", str(exc))
            return
        _apply_dialog(state, proposal)
        return
    except NotImplementedError:
        try:
            loc = locate_component(state.watch_path, name)
        except LookupError as exc:
            _info_dialog(state.window, "Can't auto-apply", str(exc))
            return
        _locate_dialog(state, loc, _current_anchor(comp))
        return
    _apply_dialog(state, proposal)


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
            state.zoom = 1.0
            state.pan_x = 30.0
            state.pan_y = 30.0
            canvas.queue_draw()
            _refresh_status(state)
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            state.zoom = min(10.0, state.zoom * 1.2)
            canvas.queue_draw()
            _refresh_status(state)
            return True
        if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            state.zoom = max(0.1, state.zoom / 1.2)
            canvas.queue_draw()
            _refresh_status(state)
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

    # 'dd' chord to delete the focused component. First 'd' arms it; a second
    # 'd' deletes; any other key cancels the pending state.
    if keyval in (Gdk.KEY_d, Gdk.KEY_D):
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

    # 'u' undo.
    if keyval in (Gdk.KEY_u, Gdk.KEY_U):
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

    # "a" — add a new component (type picker, placed near the focused one).
    if keyval in (Gdk.KEY_a, Gdk.KEY_A):
        _open_add_menu(state)
        return True

    # Enter commits the focused component's position to source.
    if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
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
        return False

    key.connect("key-pressed", on_key)
    win.add_controller(key)

    win.set_child(box)
    win.present()
    entry.grab_focus()


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
    adjusts its vertical adjustment to expose the row. Defers via
    GLib.idle_add when the row hasn't been allocated yet.
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

    def do_scroll():
        adj = sw.get_vadjustment()
        if adj is None:
            return False  # don't keep retrying
        row_alloc = row.get_allocation()
        if row_alloc.height == 0:
            return True  # not yet allocated; ask GLib to retry
        row_top = row_alloc.y
        row_bottom = row_top + row_alloc.height
        page = adj.get_page_size()
        value = adj.get_value()
        if row_top < value:
            adj.set_value(row_top)
        elif row_bottom > value + page:
            adj.set_value(row_bottom - page)
        return False  # done

    # If the row already has an allocation, scroll now; otherwise defer.
    if do_scroll():
        GLib.idle_add(do_scroll)


def _auto_name(state: _ViewerState, type_name: str) -> str:
    """Generate a unique name like 'Resistor1' for a new component."""
    existing = {getattr(c, "name", None) for c in state.project.components}
    i = 1
    while f"{type_name}{i}" in existing:
        i += 1
    return f"{type_name}{i}"


def _open_add_menu(state: _ViewerState) -> None:
    """Fuzzy picker of component types; creates one near the focused component."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
    from . import tree_editor

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
        nav = state.nav
        if nav is not None and nav.current is not None:
            comp = state.project.components[nav.current.component_index]
            ax, ay = _current_anchor(comp)
            return (round(ax + 0.5, 4), round(ay + 0.5, 4))
        # Default near top-left of the canvas in project inches.
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
        # Refresh the tree + focus the new component.
        if state.nav is not None:
            state.nav.rebuild(state.project)
            state.nav.focus_node(len(state.project.components) - 1, None)
        _refresh_tree_panel(state)
        if state.canvas is not None:
            state.canvas.queue_draw()
        win.close()

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
        if mtime != state.last_mtime:
            state.last_mtime = mtime
            _reload(state)
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
