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
        win.set_child(sw)

        # Keyboard shortcuts
        key = Gtk.EventControllerKey()
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
        # Filled in by show()
        self.canvas = None
        self.status_lbl = None
        self.window = None
        self.error_msg: str | None = None


def _status_text(state: _ViewerState) -> str:
    n = len(state.project.components)
    title = state.project.title or "untitled"
    sel = f"  ·  sel: {state.selected_name}" if state.selected_name else ""
    err = f"  ·  ⚠ {state.error_msg}" if state.error_msg else ""
    return f"{title}  ·  {n} components  ·  zoom {state.zoom:.2f}{sel}{err}"


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


def _info_dialog(parent, title: str, body: str) -> None:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    dlg = Gtk.AlertDialog()
    dlg.set_message(title)
    dlg.set_detail(body)
    dlg.show(parent)


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

    cancel_btn.connect("clicked", lambda _b: win.close())
    apply_btn.connect("clicked", lambda _b: do_apply())
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
    close_btn = Gtk.Button(label="Close  (Esc)")
    close_btn.connect("clicked", lambda _b: win.close())
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
        if keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_Escape):
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
