"""Command-line interface for pydiylc.

Subcommands:

    pydiylc convert IN OUT      # .py | .json | .diy → .diy | .json | .svg
    pydiylc render IN [--out]   # → svg (default), --dpi N for resolution
    pydiylc info FILE           # component count, warnings, breakdown

Examples::

    pydiylc convert examples/demo_lpb1_stripboard.py layout.diy
    pydiylc convert layout.diy layout.json
    pydiylc render layout.diy --out preview.svg --dpi 192
    pydiylc info layout.diy
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

from .core import Project
from .loader import project_from_json
from .reader import read_project, read_warnings


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------


def load_project(path: str | Path) -> Project:
    """Load a Project from a .py, .json, or .diy file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    suffix = p.suffix.lower()
    if suffix == ".py":
        return _load_python(p)
    if suffix == ".json":
        return project_from_json(p.read_text(encoding="utf-8"))
    if suffix == ".diy":
        return read_project(p)
    raise ValueError(f"unsupported source extension: {suffix}")


def _load_python(path: Path) -> Project:
    """Import a Python file and extract its Project.

    Recognized conventions, in order:
    1. Top-level `project = Project(...)`
    2. `def build() -> Project`
    3. Any Project instance assigned at module scope
    4. `def main() -> Project` (a Project, not None) — convenience for demos
       that double as runnable scripts
    """
    spec = importlib.util.spec_from_file_location("pydiylc_userscript", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "project") and isinstance(module.project, Project):
        return module.project
    if hasattr(module, "build") and callable(module.build):
        result = module.build()
        if isinstance(result, Project):
            return result
        raise RuntimeError(f"{path}: build() must return a Project")
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
        "`def build() -> Project`"
    )


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def save_project(project: Project, path: str | Path, *, dpi: int = 96) -> Path:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".diy":
        return project.save(p)
    if suffix == ".json":
        data = {
            "title": project.title,
            "author": project.author,
            "width_cm": project.width_cm,
            "height_cm": project.height_cm,
            "components": [_component_to_dict(c) for c in project.components],
        }
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p
    if suffix == ".svg":
        from .svg import render_svg, RenderOptions

        p.write_text(
            render_svg(project, RenderOptions(px_per_inch=dpi)), encoding="utf-8"
        )
        return p
    if suffix == ".png":
        from .cairo_render import render_png

        render_png(project, p, dpi=dpi)
        return p
    raise ValueError(f"unsupported target extension: {suffix}")


def _component_to_dict(component) -> dict:
    """Serialize a Component to its from_dict() form.

    Mirrors how the JSON loader expects to receive it: `type` plus all
    dataclass fields (Measures expanded to `{value, unit}`).
    """
    import dataclasses

    from .core import Measure

    cls_name = type(component).__name__
    # Field collision: SolderPad/TraceCut/BlankBoard have a `type` field which
    # collides with the dict discriminator. Build the body first, then merge
    # the discriminator under a renamed key when needed.
    body: dict = {}
    for f in dataclasses.fields(component):
        if f.name.startswith("_"):
            continue
        v = getattr(component, f.name)
        if isinstance(v, Measure):
            body[f.name] = {"value": v.value, "unit": v.unit}
        elif isinstance(v, (list, tuple)) and v and isinstance(v[0], tuple):
            body[f.name] = [list(p) for p in v]
        else:
            body[f.name] = v
    if "type" in body:
        # Preserve the component's `type` field; use a non-colliding key for
        # the discriminator. The loader accepts both.
        return {"_type": cls_name, **body}
    return {"type": cls_name, **body}


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        project = load_project(args.source)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"pydiylc convert: {exc}", file=sys.stderr)
        return 2
    try:
        out = save_project(project, args.target, dpi=args.dpi)
    except (ValueError, NotImplementedError) as exc:
        print(f"pydiylc convert: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {out} ({len(project.components)} components)")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    try:
        project = load_project(args.source)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"pydiylc render: {exc}", file=sys.stderr)
        return 2
    out_path = Path(args.out) if args.out else Path(args.source).with_suffix(".svg")
    if out_path.suffix.lower() not in (".svg", ".png"):
        print(
            f"pydiylc render: only .svg / .png are supported (got {out_path.suffix}); "
            "use `pydiylc convert` for other formats.",
            file=sys.stderr,
        )
        return 2
    try:
        save_project(project, out_path, dpi=args.dpi)
    except ImportError as exc:
        print(f"pydiylc render: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {out_path}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    try:
        project = load_project(args.source)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"pydiylc info: {exc}", file=sys.stderr)
        return 2

    print(f"file:     {args.source}")
    print(f"title:    {project.title}")
    if project.author:
        print(f"author:   {project.author}")
    print(f"size:     {project.width_cm:.1f} x {project.height_cm:.1f} cm")
    print(f"grid:     {project.grid_inches} in")
    print(f"version:  {'.'.join(str(x) for x in project.file_version)}")
    print(f"total:    {len(project.components)} components")

    counts = Counter(type(c).__name__ for c in project.components)
    if counts:
        print("\nby type:")
        for name, n in counts.most_common():
            print(f"  {n:4d}  {name}")

    warnings = read_warnings(project)
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings[:20]:
            print(f"  - {w}")
        if len(warnings) > 20:
            print(f"  ... and {len(warnings) - 20} more")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pydiylc",
        description="Convert, render, and inspect pydiylc layouts.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p_convert = sub.add_parser(
        "convert",
        help="Convert between formats (.py / .json / .diy → .diy / .json / .svg).",
    )
    p_convert.add_argument("source", help="input file")
    p_convert.add_argument("target", help="output file (.diy / .json / .svg)")
    p_convert.add_argument(
        "--dpi", type=int, default=96, help="SVG resolution (default 96)"
    )
    p_convert.set_defaults(func=cmd_convert)

    p_render = sub.add_parser("render", help="Render a layout to SVG.")
    p_render.add_argument("source", help="input file")
    p_render.add_argument("--out", help="output path (default: <source>.svg)")
    p_render.add_argument("--dpi", type=int, default=96)
    p_render.set_defaults(func=cmd_render)

    p_info = sub.add_parser("info", help="Summarize a layout file.")
    p_info.add_argument("source", help="input file")
    p_info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
