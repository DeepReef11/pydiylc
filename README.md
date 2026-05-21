# pydiylc

Python emitter for [DIYLC](https://github.com/bancika/diy-layout-creator) `.diy`
files. Write circuit layouts in code, open them in DIYLC.

This is an *emitter*, not a viewer or full reimplementation. DIYLC stays as the
rendering engine — pydiylc just produces files it can open.

## Status

Pre-alpha. Current component set: boards (`BlankBoard`, `PerfBoard`),
passives (`Resistor`, `RadialFilmCapacitor`, `RadialCeramicDiskCapacitor`,
`RadialElectrolytic`, `PotentiometerPanel`), semiconductors (`DiodePlastic`,
`LED`, `TransistorTO92`, `DIL_IC`), connectivity (`CopperTrace`, `Jumper`,
`HookupWire`, `SolderPad`), and `Label`.

## AI-friendly by design

- [`LLMS.txt`](./LLMS.txt) — one-screen overview meant to be fed to a coding
  assistant. Lists every component, the values its enum fields accept, and the
  value-string parsing rules.
- [`catalog.json`](./catalog.json) — machine-readable schema of every
  component, regenerated with `python -m pydiylc.catalog`. Fields, types,
  defaults, enum choices, and Measure units. Use this for codegen,
  prompt-stuffing, or downstream validation.
- Every component validates its enum fields at construction with a clear
  `ValueError` listing the allowed values.

## Install

```bash
pip install -e .
```

## Use

```python
from pydiylc import Project, PerfBoard, Resistor, SolderPad, CopperTrace

p = Project(title="Booster", width_cm=10, height_cm=8)
p.add(PerfBoard("Board1", x1=1.0, y1=1.0, x2=3.0, y2=2.5))
p.add(Resistor("R1", x1=1.2, y1=1.2, x2=1.2, y2=1.8, value="10K"))
p.add(SolderPad("P1", x=1.2, y=1.2))
p.add(SolderPad("P2", x=1.2, y=1.8))
p.add(CopperTrace("T1", points=[(1.2, 1.8), (2.0, 1.8)]))
p.save("booster.diy")
```

Or from JSON (the preferred path for LLMs / external tools):

```python
from pydiylc import Project

Project.from_dict({
    "title": "Booster",
    "components": [
        {"type": "PerfBoard", "name": "Board1", "x1": 1.0, "y1": 1.0, "x2": 3.0, "y2": 2.5},
        {"type": "Resistor", "name": "R1", "x1": 1.2, "y1": 1.2, "x2": 1.2, "y2": 1.8, "value": "10K"},
    ],
}).save("booster.diy")
```

Open `booster.diy` in DIYLC.

## File format

DIYLC ships file format v4.x. v5.x of the application reuses the same on-disk
schema with additive components. pydiylc targets that schema and currently
writes `<fileVersion>5.7.0</fileVersion>` so recent DIYLC builds open without a
"created with older version" warning.

Coordinates are in inches by default (DIYLC's grid is `0.1 in`).

## License

GPL-3.0-or-later, matching upstream DIYLC.
