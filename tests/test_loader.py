from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from pydiylc import (
    Project,
    project_from_dict,
    project_from_json,
    component_from_dict,
    Resistor,
)


def test_minimal_dict_to_project():
    p = project_from_dict({"title": "x", "components": []})
    assert p.title == "x"
    assert p.components == []


def test_components_get_constructed():
    p = project_from_dict(
        {
            "components": [
                {"type": "Resistor", "name": "R1", "x1": 0, "y1": 0, "x2": 0, "y2": 0.5, "value": "10K"},
            ]
        }
    )
    assert isinstance(p.components[0], Resistor)
    assert p.components[0].value == "10K"


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown component type"):
        component_from_dict({"type": "NotAComponent", "name": "x"})


def test_missing_type_raises():
    with pytest.raises(ValueError, match="needs a 'type' key"):
        component_from_dict({"name": "x"})


def test_measure_field_accepts_dict():
    c = component_from_dict(
        {
            "type": "Resistor",
            "name": "R1",
            "x1": 0,
            "y1": 0,
            "x2": 0,
            "y2": 0.5,
            "length": {"value": 0.5, "unit": "in"},
            "width": {"value": 3.2, "unit": "mm"},
        }
    )
    assert c.length.value == 0.5 and c.length.unit == "in"
    assert c.width.value == 3.2 and c.width.unit == "mm"


def test_measure_field_accepts_bare_number():
    c = component_from_dict(
        {"type": "SolderPad", "name": "P1", "x": 0, "y": 0, "size": 0.12}
    )
    assert c.size.value == 0.12
    assert c.size.unit == "in"


def test_from_json_string():
    text = json.dumps({"components": [{"type": "SolderPad", "name": "P1", "x": 0, "y": 0}]})
    p = project_from_json(text)
    assert len(p.components) == 1


def test_round_trip_emits_valid_xml():
    doc = {
        "title": "rt",
        "components": [
            {"type": "PerfBoard", "name": "Board1", "x1": 1.0, "y1": 1.0, "x2": 2.0, "y2": 1.5},
            {"type": "DIL_IC", "name": "U1", "x": 1.5, "y": 1.2, "value": "TL072", "pin_count": "_8"},
            {"type": "TransistorTO92", "name": "Q1", "x": 1.2, "y": 1.4, "value": "2N5088"},
            {"type": "PotentiometerPanel", "name": "VR1", "x": 1.8, "y": 1.4, "resistance": "100K"},
        ],
    }
    p = Project.from_dict(doc)
    ET.fromstring(p.to_xml())  # must parse


def test_project_classmethod_from_json():
    p = Project.from_json('{"title":"x","components":[]}')
    assert p.title == "x"


def test_validation_still_fires_via_loader():
    with pytest.raises(ValueError, match="Resistor.power"):
        project_from_dict(
            {
                "components": [
                    {"type": "Resistor", "name": "R1", "x1": 0, "y1": 0, "x2": 0, "y2": 0.5, "power": "half"},
                ]
            }
        )
