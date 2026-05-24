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
    The fallback exists because several components (SolderPad, TraceCut,
    BlankBoard, OpenJack1_4, ClosedJack1_4, CliffJack1_4, NeutrikJack1_4,
    Pad, …) have a ``type`` field of their own, so when you set such a
    field the dict has a key collision with the discriminator. Use
    ``"_type"`` for the class name in that case.
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
            # Two failure modes look identical from here:
            #   1) typo: 'RadialCeramicCapacitor' → meant RadialCeramicDiskCapacitor
            #   2) key collision: caller wrote {'type': 'Cls', 'type': 'FieldVal'}
            #      and Python kept only the second, dropping the class name.
            # Suggest close matches (covers #1), and mention the collision
            # pattern (covers #2). The LLM picks whichever applies.
            import difflib
            name_hint = f" (name={d['name']!r})" if d.get("name") else ""
            suggestions = difflib.get_close_matches(
                d["type"], list(_BY_NAME), n=3, cutoff=0.5
            )
            sugg_str = (
                f" Did you mean: {', '.join(suggestions)}?"
                if suggestions else ""
            )
            raise ValueError(
                f"component dict{name_hint} has type={d['type']!r}, which "
                f"isn't a pydiylc class name.{sugg_str} If the name looks "
                "right, you may have a key collision: "
                "{'type': 'OpenJack1_4', 'name': 'J1', 'type': 'MONO'} drops "
                "the class name (Python/JSON keep the last 'type'). "
                "Use '_type' for the class and leave 'type' for the "
                "component's own field — "
                "{'_type': 'OpenJack1_4', 'name': 'J1', 'type': 'MONO'}."
            )
    else:
        raise ValueError(
            "component dict needs a 'type' or '_type' key naming a pydiylc "
            "class (e.g. {'type': 'Resistor', ...})"
        )
    if type_name not in _BY_NAME:
        raise ValueError(
            f"unknown component type {type_name!r}; known types: {sorted(_BY_NAME)}"
        )
    cls = _BY_NAME[type_name]

    measure_fields = _measure_fields(cls)
    for k in list(kwargs):
        if k in measure_fields:
            kwargs[k] = _coerce_measure(kwargs[k])

    try:
        return cls(**kwargs)
    except TypeError as e:
        # Likely shape mismatch (single-anchor vs two-point) or a single
        # misnamed field. Tell the LLM what's accepted and suggest the
        # closest match for the offending field.
        import dataclasses
        import difflib
        import re
        accepted = sorted(f.name for f in dataclasses.fields(cls))
        passed = sorted(kwargs)
        # Pick out the unexpected argument from the TypeError message.
        bad_field_match = re.search(
            r"unexpected keyword argument '([^']+)'", str(e)
        )
        field_hint = ""
        if bad_field_match:
            bad = bad_field_match.group(1)
            suggestions = difflib.get_close_matches(
                bad, accepted, n=3, cutoff=0.5
            )
            if suggestions:
                field_hint = (
                    f" Did you mean {', '.join(repr(s) for s in suggestions)}?"
                )
        # Hint about the most common shape confusion: x/y vs x1/y1/x2/y2.
        wants_xy = {"x", "y"}.issubset(accepted)
        wants_x1y1 = {"x1", "y1", "x2", "y2"}.issubset(accepted)
        shape_hint = ""
        if wants_xy and {"x1", "y1"}.intersection(passed):
            shape_hint = (
                f" {type_name} is a single-anchor component — use x/y, "
                "not x1/y1/x2/y2."
            )
        elif wants_x1y1 and {"x", "y"}.intersection(passed):
            shape_hint = (
                f" {type_name} is a two-point component — use "
                "x1/y1/x2/y2, not x/y."
            )
        name_hint = f" (name={kwargs.get('name')!r})" if kwargs.get("name") else ""
        raise ValueError(
            f"can't build {type_name}{name_hint}: {e}.{field_hint}"
            f"{shape_hint} Accepted fields: {accepted}."
        ) from None


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
