"""MCP (Model Context Protocol) server for pydiylc.

Exposes pydiylc as a set of tools any MCP-capable LLM client can call.
The intended workflow:

1. Client reads ``catalog.json`` (or ``list_component_types``) once.
2. Client constructs a layout by calling ``add_component`` repeatedly
   (or one-shot via ``create_project_from_dict``).
3. Client calls ``save`` to emit `.diy`, or ``render_svg`` for a preview.

Run::

    pip install pydiylc[mcp]
    pydiylc-mcp                 # stdio transport (the MCP default)

The MCP SDK is an optional dependency. Importing this module without it
raises ImportError with an install hint.
"""

from __future__ import annotations

from pathlib import Path

from .core import Project
from .catalog import build_catalog
from .loader import project_from_dict, component_from_dict
from .reader import read_project, read_warnings


def _require_mcp():
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "pydiylc.mcp_server requires the MCP SDK.\n"
            "  pip install pydiylc[mcp]\n"
            "  (or: pip install 'mcp[cli]')"
        ) from exc


def has_mcp() -> bool:
    try:
        _require_mcp()
        return True
    except ImportError:
        return False


# In-memory project store. Keyed by string id chosen by the client (defaulting
# to "default"). Multiple parallel projects are supported.
_PROJECTS: dict[str, Project] = {}


def _get(project_id: str) -> Project:
    if project_id not in _PROJECTS:
        raise KeyError(f"no project with id {project_id!r}; call create_project first")
    return _PROJECTS[project_id]


def build_server():
    """Construct the FastMCP app. Separate function so tests can poke it."""
    _require_mcp()
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(name="pydiylc")

    # ---- Catalog --------------------------------------------------------

    @server.tool()
    def list_component_types() -> dict:
        """Return the machine-readable catalog of every supported component."""
        return build_catalog()

    # ---- Project lifecycle ---------------------------------------------

    @server.tool()
    def create_project(
        project_id: str = "default",
        title: str = "New Project",
        width_cm: float = 29.0,
        height_cm: float = 21.0,
    ) -> dict:
        """Create a new empty Project."""
        p = Project(title=title, width_cm=width_cm, height_cm=height_cm)
        _PROJECTS[project_id] = p
        return {"project_id": project_id, "title": p.title, "components": 0}

    @server.tool()
    def create_project_from_dict(payload: dict, project_id: str = "default") -> dict:
        """Build a Project from a JSON-loader-format dict in one call."""
        p = project_from_dict(payload)
        _PROJECTS[project_id] = p
        return {"project_id": project_id, "title": p.title, "components": len(p.components)}

    @server.tool()
    def add_component(component: dict, project_id: str = "default") -> dict:
        """Add a single component to a project. See list_component_types for fields."""
        p = _get(project_id)
        c = component_from_dict(component)
        p.add(c)
        return {"added": c.name, "type": type(c).__name__, "total_components": len(p.components)}

    @server.tool()
    def list_components(project_id: str = "default") -> list[dict]:
        """List the components currently in a project."""
        p = _get(project_id)
        return [
            {"index": i, "type": type(c).__name__, "name": getattr(c, "name", "?")}
            for i, c in enumerate(p.components)
        ]

    @server.tool()
    def remove_component(name: str, project_id: str = "default") -> dict:
        """Remove the first component matching `name`."""
        p = _get(project_id)
        for i, c in enumerate(p.components):
            if getattr(c, "name", None) == name:
                del p.components[i]
                return {"removed": True, "remaining": len(p.components)}
        return {"removed": False, "remaining": len(p.components)}

    # ---- Save / render -------------------------------------------------

    @server.tool()
    def save(path: str, project_id: str = "default") -> dict:
        """Save the project to a `.diy` file."""
        p = _get(project_id)
        out = p.save(path)
        return {"path": str(Path(out).resolve()), "components": len(p.components)}

    @server.tool()
    def render_svg(path: str, project_id: str = "default", dpi: int = 96) -> dict:
        """Render the project to an SVG preview file."""
        from .svg import render_svg as _render_svg, RenderOptions

        p = _get(project_id)
        out = Path(path)
        out.write_text(
            _render_svg(p, RenderOptions(px_per_inch=dpi)), encoding="utf-8"
        )
        return {"path": str(out.resolve())}

    @server.tool()
    def to_json(project_id: str = "default") -> dict:
        """Serialize the project to JSON (round-trip-clean)."""
        from .cli import _component_to_dict

        p = _get(project_id)
        return {
            "title": p.title,
            "author": p.author,
            "width_cm": p.width_cm,
            "height_cm": p.height_cm,
            "components": [_component_to_dict(c) for c in p.components],
        }

    # ---- Read .diy ------------------------------------------------------

    @server.tool()
    def read_diy(path: str, project_id: str = "default") -> dict:
        """Parse a .diy file from disk into a project slot."""
        p = read_project(path)
        _PROJECTS[project_id] = p
        return {
            "project_id": project_id,
            "title": p.title,
            "components": len(p.components),
            "warnings": read_warnings(p),
        }

    return server


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point. Runs the server on stdio."""
    try:
        server = build_server()
    except ImportError as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 2
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
