"""Build a Project from a plain dict / JSON document.

This is the canonical interchange format for tools (and LLMs) that want to
emit pydiylc layouts without writing Python. See ``LLMS.txt`` for the
schema's prose description; ``catalog.json`` is its machine-readable spec.

Example document::

    {
      "title": "Booster",
      "width_cm": 10,
      "height_cm": 8,
      "components": [
        {"type": "PerfBoard", "name": "Board1", "x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 2.5},
        {"type": "Resistor", "name": "R1", "x1": 1.2, "y1": 1.2, "x2": 1.2, "y2": 1.8,
         "value": "10K"},
        {"type": "SolderPad", "name": "P1", "x": 1.2, "y": 1.2}
      ]
    }

Each component dict must include a ``type`` field naming a pydiylc class
(e.g. ``"Resistor"``). Remaining keys are passed to the constructor as
kwargs. Measure-typed fields accept either ``{"value": 0.1, "unit": "in"}``
or a bare number (interpreted as inches).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import Project, Measure
from .components import ALL_COMPONENTS, Component


_BY_NAME: dict[str, type[Component]] = {c.__name__: c for c in ALL_COMPONENTS}


def _coerce_measure(value: Any, default_unit: str = "in") -> Measure:
    if isinstance(value, Measure):
        return value
    if isinstance(value, (int, float)):
        return Measure(float(value), default_unit)
    if isinstance(value, dict):
        return Measure(float(value["value"]), value.get("unit", default_unit))
    raise ValueError(f"can't coerce to Measure: {value!r}")


def _measure_fields(cls: type[Component]) -> set[str]:
    import dataclasses

    out: set[str] = set()
    for f in dataclasses.fields(cls):
        t = f.type
        if t is Measure or (isinstance(t, str) and t == "Measure"):
            out.add(f.name)
    return out


def component_from_dict(d: dict[str, Any]) -> Component:
    """Construct a single component from a dict.

    The component class is taken from ``"_type"`` (preferred) or ``"type"``.
    The fallback exists because a few components (SolderPad, TraceCut,
    BlankBoard) have a ``type`` field of their own, so they're serialized
    with ``"_type"`` to avoid the collision.
    """
    if "_type" in d:
        type_name = d["_type"]
        kwargs = {k: v for k, v in d.items() if k != "_type"}
    elif "type" in d:
        # Only treat `type` as the discriminator when it names a pydiylc class.
        # Otherwise it's a component field (SolderPad.type="ROUND" etc.) and
        # the discriminator must be `_type` elsewhere.
        if d["type"] in _BY_NAME:
            type_name = d["type"]
            kwargs = {k: v for k, v in d.items() if k != "type"}
        else:
            raise ValueError(
                "component dict has a 'type' field that doesn't name a "
                "pydiylc class. Use '_type' for the class discriminator."
            )
    else:
        raise ValueError("component dict needs a 'type' or '_type' key naming a pydiylc class")
    if type_name not in _BY_NAME:
        raise ValueError(
            f"unknown component type {type_name!r}; known types: {sorted(_BY_NAME)}"
        )
    cls = _BY_NAME[type_name]

    measure_fields = _measure_fields(cls)
    for k in list(kwargs):
        if k in measure_fields:
            kwargs[k] = _coerce_measure(kwargs[k])

    return cls(**kwargs)


def project_from_dict(d: dict[str, Any]) -> Project:
    """Build a Project from a dict matching the LLM-facing schema."""
    project_kwargs = {k: v for k, v in d.items() if k != "components"}
    p = Project(**project_kwargs)
    for cdict in d.get("components", []):
        p.add(component_from_dict(cdict))
    return p


def project_from_json(text: str) -> Project:
    """Parse a JSON string and build a Project."""
    return project_from_dict(json.loads(text))


def project_from_json_file(path: str | Path) -> Project:
    """Load a JSON document from disk and build a Project."""
    return project_from_json(Path(path).read_text(encoding="utf-8"))
