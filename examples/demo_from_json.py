"""Demo: build a layout from a JSON document (no Python imports per
component). This is the path intended for LLMs and external tools.

The JSON schema is the same one described in `LLMS.txt` — every component
has a `type` field naming a pydiylc class, the rest are kwargs.
"""

import json

from pydiylc import Project


DOC = {
    "title": "From JSON",
    "width_cm": 10,
    "height_cm": 8,
    "components": [
        {"type": "PerfBoard", "name": "Board1", "x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 2.0},
        {"type": "TransistorTO92", "name": "Q1", "x": 1.5, "y": 1.3,
         "value": "2N5088", "pinout": "BJT_EBC"},
        {"type": "Resistor", "name": "R1", "x1": 1.5, "y1": 1.3,
         "x2": 1.5, "y2": 1.0, "value": "1M"},
        {"type": "Resistor", "name": "R2", "x1": 1.7, "y1": 1.3,
         "x2": 1.7, "y2": 1.0, "value": "10K"},
        {"type": "RadialFilmCapacitor", "name": "C1", "x1": 1.3, "y1": 1.3,
         "x2": 1.5, "y2": 1.3, "value": "100nF"},
        {"type": "RadialElectrolytic", "name": "C2", "x1": 1.7, "y1": 1.3,
         "x2": 1.9, "y2": 1.3, "value": "1uF"},
        {"type": "CopperTrace", "name": "T_gnd",
         "points": [(1.3, 1.6), (1.9, 1.6)]},
        {"type": "Label", "name": "L1", "x": 1.6, "y": 0.85,
         "text": "LPB-1 (JSON)", "font_size": 10},
    ],
}


def main() -> None:
    # Could equivalently be: Project.from_json(json.dumps(DOC))
    p = Project.from_dict(DOC)
    out = p.save("from_json.diy")
    print(f"wrote {out} from a {len(json.dumps(DOC))}-byte JSON doc")
    print(f"  -> {len(p.components)} components")


if __name__ == "__main__":
    main()
