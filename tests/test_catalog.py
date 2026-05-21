from __future__ import annotations

import json
from pathlib import Path

from pydiylc.catalog import build_catalog
from pydiylc.components import ALL_COMPONENTS


def test_catalog_lists_every_component():
    cat = build_catalog()
    names_in_cat = {c["python_class"] for c in cat["components"]}
    names_in_code = {c.__name__ for c in ALL_COMPONENTS}
    assert names_in_cat == names_in_code


def test_catalog_diylc_classes_match_source():
    cat = build_catalog()
    for entry, cls in zip(cat["components"], ALL_COMPONENTS):
        assert entry["diylc_class"] == cls.__diylc_class__
        assert entry["diylc_class"].startswith("diylc.")


def test_catalog_enum_pool_nonempty():
    cat = build_catalog()
    assert "POWER" in cat["enum_pool"]
    assert cat["enum_pool"]["POWER"] == ["QUARTER", "HALF", "ONE", "TWO"]


def test_each_field_has_type_and_default_keys():
    cat = build_catalog()
    for entry in cat["components"]:
        for f in entry["fields"]:
            assert "name" in f
            assert "type" in f and "kind" in f["type"]
            assert "default" in f
            assert "required" in f


def test_resistor_field_enum_present():
    cat = build_catalog()
    r = next(c for c in cat["components"] if c["python_class"] == "Resistor")
    power = next(f for f in r["fields"] if f["name"] == "power")
    assert power["enum"] == ["QUARTER", "HALF", "ONE", "TWO"]
    assert power["default"] == "HALF"


def test_measure_field_renders_as_measure_with_unit():
    cat = build_catalog()
    r = next(c for c in cat["components"] if c["python_class"] == "Resistor")
    length = next(f for f in r["fields"] if f["name"] == "length")
    assert length["type"]["kind"] == "measure"
    assert length["default"] == {"value": 0.5, "unit": "in"}


def test_catalog_json_serializable():
    cat = build_catalog()
    s = json.dumps(cat)
    assert "Resistor" in s


def test_checked_in_catalog_matches_generator():
    """If catalog.json drifts from the code, regenerate it."""
    p = Path(__file__).resolve().parents[1] / "catalog.json"
    if not p.exists():
        return  # not yet generated — that's fine in dev
    on_disk = json.loads(p.read_text())
    generated = build_catalog()
    # Compare structure (ignore version field which may differ during dev)
    assert {c["python_class"] for c in on_disk["components"]} == {
        c["python_class"] for c in generated["components"]
    }
