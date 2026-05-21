"""Machine-readable catalog of every pydiylc component.

Build with::

    python -m pydiylc.catalog > catalog.json

Or load programmatically::

    from pydiylc.catalog import build_catalog
    schema = build_catalog()

The output is intended for LLMs and codegen — it lists every component with
its fields, types, defaults, enum choices, and Measure-typed fields with
their default unit.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sys
from typing import Any

from .core import Measure
from .components import ALL_COMPONENTS, Component
from . import enums as E


_PRIMITIVE_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

_MEASURE_HINTS = {
    "thickness": "length",
    "size": "length",
    "hole_size": "length",
    "length": "length",
    "width": "length",
    "height": "length",
    "pin_spacing": "length",
    "spacing": "length",
}


def _type_descriptor(f: dataclasses.Field) -> dict[str, Any]:
    t = f.type
    # Dataclass field types arrive as strings under `from __future__ import annotations`.
    # We accept both string names and actual types.
    if isinstance(t, type) and t in _PRIMITIVE_TYPES:
        return {"kind": _PRIMITIVE_TYPES[t]}
    name = t if isinstance(t, str) else getattr(t, "__name__", str(t))
    if name == "Measure" or t is Measure:
        return {"kind": "measure", "purpose": _MEASURE_HINTS.get(f.name, "length")}
    primitive_names = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
    if name in primitive_names:
        return {"kind": primitive_names[name]}
    if name.startswith("Sequence") or name.startswith("list") or name.startswith("tuple"):
        return {"kind": "points"}
    return {"kind": name}


def _default(f: dataclasses.Field) -> Any:
    if f.default is not dataclasses.MISSING:
        return _serialize(f.default)
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        try:
            return _serialize(f.default_factory())  # type: ignore[misc]
        except Exception:
            return None
    return None  # required


def _serialize(v: Any) -> Any:
    if isinstance(v, Measure):
        return {"value": v.value, "unit": v.unit}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _component_schema(cls: type[Component]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    enums = cls.__enums__ or {}
    for f in dataclasses.fields(cls):
        if f.name.startswith("_"):
            continue
        desc = _type_descriptor(f)
        entry: dict[str, Any] = {
            "name": f.name,
            "type": desc,
            "default": _default(f),
            "required": f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING,  # type: ignore[misc]
        }
        if f.name in enums:
            entry["enum"] = list(enums[f.name])
        fields.append(entry)
    doc = inspect.getdoc(cls) or ""
    return {
        "python_class": cls.__name__,
        "diylc_class": cls.__diylc_class__,
        "doc": doc,
        "fields": fields,
    }


def build_catalog() -> dict[str, Any]:
    """Return the full catalog as a plain dict, JSON-serializable."""
    enum_pool = {
        name: list(value)
        for name, value in vars(E).items()
        if not name.startswith("_") and isinstance(value, tuple) and value and isinstance(value[0], str)
    }
    return {
        "schema_version": 1,
        "pydiylc_version": _version(),
        "diylc_file_version_target": "5.7.0",
        "coordinate_units": "inches by default (project grid is 0.1 in)",
        "enum_pool": enum_pool,
        "components": [_component_schema(c) for c in ALL_COMPONENTS],
    }


def _version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "0.0.0"


def bundled_catalog_path() -> "Path | None":
    """Return the path to the catalog.json shipped with the installed package.

    Returns None if the package was installed without the data file (e.g.
    from an editable source checkout without running hatch build).
    """
    from pathlib import Path

    here = Path(__file__).resolve().parent
    candidate = here / "data" / "catalog.json"
    if candidate.exists():
        return candidate
    # Fall back to repo-root catalog.json when running from source.
    repo_root = here.parent.parent
    candidate = repo_root / "catalog.json"
    if candidate.exists():
        return candidate
    return None


def bundled_llms_txt_path() -> "Path | None":
    """Same as bundled_catalog_path but for LLMS.txt."""
    from pathlib import Path

    here = Path(__file__).resolve().parent
    candidate = here / "data" / "LLMS.txt"
    if candidate.exists():
        return candidate
    repo_root = here.parent.parent
    candidate = repo_root / "LLMS.txt"
    if candidate.exists():
        return candidate
    return None


def main() -> None:
    json.dump(build_catalog(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
