"""Field-level .diy round-trip: what you write is what you read back.

The corpus round-trip test checks component count + type signature only, so
an emitter that forgets a field (or a reader that maps a tag to the wrong
name) slips through silently. This sweep constructs every component type,
tweaks each tweakable field one at a time, saves, re-reads, and compares
every dataclass field.

Tweakable means predictable: bools flip, enums move to another allowed
value, 6-hex color strings change, Measures change value. Free-form strings
(component values like "10K") have per-class parsing rules, so they're
covered by targeted tests instead.
"""

from __future__ import annotations

import dataclasses

import pytest

from pydiylc import Project
from pydiylc.components import ALL_COMPONENTS
from pydiylc.core import Measure


def _base_kwargs(cls) -> dict | None:
    """Fill just the required fields of a component class."""
    kw: dict = {}
    for f in dataclasses.fields(cls):
        if (
            f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        ):
            continue
        if f.name == "name":
            kw["name"] = "X1"
        elif f.name in ("x", "y", "x1", "y1"):
            kw[f.name] = 2.0
        elif f.name in ("x2", "y2"):
            kw[f.name] = 3.0
        elif f.name == "points":
            kw["points"] = [(2.0, 2.0), (3.0, 2.0), (3.0, 3.0)]
        elif f.name == "text":
            kw["text"] = "hi"
        elif f.name == "value":
            kw["value"] = "1"
        else:
            return None
    return kw


def _is_hex_color(v) -> bool:
    return (
        isinstance(v, str)
        and len(v) == 6
        and all(c in "0123456789abcdefABCDEF" for c in v)
    )


def _tweak(cls, f: dataclasses.Field, current):
    """A new, predictable value for the field — or None to skip it."""
    enums = getattr(cls, "__enums__", None) or {}
    if f.name in enums:
        options = [v for v in enums[f.name] if v != current]
        return options[0] if options else None
    if isinstance(current, bool):
        return not current
    if isinstance(current, Measure):
        return Measure(round(current.value + 0.05, 4), current.unit)
    if _is_hex_color(current):
        return "123abc" if current.lower() != "123abc" else "abc123"
    if f.name == "text":
        return "tweaked"
    return None


def _cases():
    for cls in ALL_COMPONENTS:
        base = _base_kwargs(cls)
        if base is None:
            continue
        for f in dataclasses.fields(cls):
            if f.name.startswith("_") or f.name in base:
                continue
            try:
                current = getattr(cls(**base), f.name)
            except Exception:
                continue
            new = _tweak(cls, f, current)
            if new is None or new == current:
                continue
            yield pytest.param(cls, base, f.name, new, id=f"{cls.__name__}.{f.name}")


# Fields that intentionally do not round-trip verbatim. Keep this list empty
# unless a divergence is genuinely by design — and say why.
_KNOWN_EXCEPTIONS: set[tuple[str, str]] = set()


@pytest.mark.parametrize("cls, base, field_name, new_value", _cases())
def test_field_survives_diy_round_trip(tmp_path, cls, base, field_name, new_value):
    if (cls.__name__, field_name) in _KNOWN_EXCEPTIONS:
        pytest.skip("documented round-trip exception")
    comp = cls(**{**base, field_name: new_value})
    p = Project(title="t")
    p.add(comp)
    f = tmp_path / "rt.diy"
    p.save(f)
    p2 = Project.read(f)
    assert p2.components, f"{cls.__name__} dropped on read"
    got = getattr(p2.components[0], field_name)
    assert got == new_value, (
        f"{cls.__name__}.{field_name}: wrote {new_value!r}, read back {got!r}"
    )
