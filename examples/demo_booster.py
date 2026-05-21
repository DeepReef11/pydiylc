"""Tiny demo: a one-transistor-ish placeholder on a perfboard.

Produces booster.diy in the current directory. Open it in DIYLC.
"""

from pydiylc import (
    Project,
    PerfBoard,
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    SolderPad,
    CopperTrace,
    Jumper,
    Label,
)


def build() -> Project:
    p = Project(title="pydiylc demo - LPB-1 ish", width_cm=15, height_cm=10)

    # 1 in x 0.7 in perfboard at (1, 1)
    p.add(PerfBoard("Board1", x1=1.0, y1=1.0, x2=2.0, y2=1.7))

    # input cap
    p.add(SolderPad("Pin", x=1.1, y=1.1))
    p.add(SolderPad("P1", x=1.3, y=1.1))
    p.add(RadialFilmCapacitor("C1", x1=1.1, y1=1.1, x2=1.3, y2=1.1, value="100nF"))

    # base resistor
    p.add(SolderPad("P2", x=1.3, y=1.3))
    p.add(Resistor("R1", x1=1.3, y1=1.1, x2=1.3, y2=1.3, value="470K"))

    # collector resistor
    p.add(SolderPad("P3", x=1.6, y=1.1))
    p.add(Resistor("R2", x1=1.6, y1=1.1, x2=1.6, y2=1.3, value="10K"))

    # output cap
    p.add(SolderPad("P4", x=1.8, y=1.1))
    p.add(SolderPad("Pout", x=1.9, y=1.1))
    p.add(RadialElectrolytic("C2", x1=1.8, y1=1.1, x2=1.9, y2=1.1, value="1uF"))

    # ground rail
    p.add(CopperTrace("GND", points=[(1.1, 1.6), (1.9, 1.6)]))
    p.add(Jumper("J1", x1=1.3, y1=1.3, x2=1.3, y2=1.6))

    p.add(Label("L1", x=1.5, y=0.95, text="pydiylc booster", font_size=10))

    return p


def main() -> None:
    p = build()
    out = p.save("booster.diy")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
