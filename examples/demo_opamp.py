"""Demo: a TL072 opamp buffer stage on a perfboard with a volume pot.

Shows DIL_IC, PotentiometerPanel, electrolytic + film caps, traces, and
the `grid_snap` helper for keeping coordinates on the 0.1 in grid.
"""

from pydiylc import (
    Project,
    PerfBoard,
    DIL_IC,
    PotentiometerPanel,
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    SolderPad,
    CopperTrace,
    Label,
)


def grid_snap(v: float, grid: float = 0.1) -> float:
    """Snap to the nearest grid line (default 0.1 in)."""
    return round(v / grid) * grid


def main() -> None:
    p = Project(title="TL072 buffer + volume", width_cm=15, height_cm=10)

    # 2 x 1.2 inch perfboard
    p.add(PerfBoard("Board1", 1.0, 1.0, 3.0, 2.2))

    # Opamp at (1.6, 1.4) — pin 1 corner
    p.add(DIL_IC("U1", x=1.6, y=1.4, value="TL072", pin_count="_8"))

    # Input cap + bias resistor on pin 3 (non-inverting input)
    p.add(SolderPad("P_in", x=1.2, y=1.4))
    p.add(SolderPad("P_in2", x=1.4, y=1.4))
    p.add(RadialFilmCapacitor("C1", 1.2, 1.4, 1.4, 1.4, value="100nF"))
    p.add(Resistor("R1", 1.4, 1.4, 1.4, 1.7, value="1M"))  # to ground

    # Feedback resistor pin 1 -> pin 2
    p.add(Resistor("R2", 1.6, 1.4, 1.6, 1.7, value="10K"))

    # Output cap on pin 1
    p.add(SolderPad("P_out", x=2.0, y=1.4))
    p.add(SolderPad("P_out2", x=2.2, y=1.4))
    p.add(RadialElectrolytic("C2", 2.0, 1.4, 2.2, 1.4, value="10uF"))

    # Volume pot below the board
    p.add(PotentiometerPanel("VR1", x=2.4, y=2.6, resistance="100K", taper="LOG"))

    # Ground rail at y=1.7
    p.add(CopperTrace("GND", points=[(1.2, 1.7), (2.4, 1.7)]))

    # Labels
    p.add(Label("L_in", x=1.1, y=1.35, text="IN", font_size=10))
    p.add(Label("L_out", x=2.3, y=1.35, text="OUT", font_size=10))
    p.add(Label("L_vol", x=2.4, y=2.4, text="VOLUME", font_size=10))

    out = p.save("opamp.diy")
    print(f"wrote {out} with {len(p.components)} components")
    print(f"grid_snap(1.234) = {grid_snap(1.234)}")


if __name__ == "__main__":
    main()
