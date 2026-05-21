"""Demo: a full LPB-1 booster pedal on stripboard.

Shows VeroBoard + TraceCut + a 3PDT bypass foot switch + DC and 1/4" jacks
+ a 100K log volume pot — the whole canonical pedal stack.

LPB-1 schematic in brief:
    - input cap -> 1M bias resistor to ground -> base of 2N5088
    - collector of 2N5088 -> 10K to +9V, output cap -> volume pot
    - emitter to ground via 1K
"""

from pydiylc import (
    Project,
    VeroBoard,
    TraceCut,
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    TransistorTO92,
    PotentiometerPanel,
    MiniToggleSwitch,
    PlasticDCJack,
    OpenJack1_4,
    SolderPad,
    HookupWire,
    Label,
)


def build() -> Project:
    p = Project(title="LPB-1 booster", width_cm=18, height_cm=12)

    # 1.2" x 0.7" stripboard (12 cols x 7 rows on 0.1in grid), strips horizontal
    p.add(VeroBoard("Board1", x1=1.0, y1=1.0, x2=2.2, y2=1.7, orientation="HORIZONTAL"))

    # Strip cuts to isolate sections — needed under transistor pins
    p.add(TraceCut("Cut1", x=1.5, y=1.3, orientation="HORIZONTAL"))
    p.add(TraceCut("Cut2", x=1.7, y=1.3, orientation="HORIZONTAL"))
    p.add(TraceCut("Cut3", x=1.5, y=1.5, orientation="HORIZONTAL"))

    # 2N5088 NPN with E-B-C pinout (the std 2N5088 datasheet pinout)
    p.add(TransistorTO92("Q1", x=1.6, y=1.3, value="2N5088", pinout="BJT_EBC"))

    # Input cap (100n film) and bias resistor (1M to ground)
    p.add(SolderPad("PadIn", x=1.1, y=1.4))
    p.add(RadialFilmCapacitor("C1", 1.1, 1.4, 1.4, 1.4, value="100nF"))
    p.add(Resistor("R1", 1.5, 1.4, 1.5, 1.6, value="1M"))   # base -> gnd
    p.add(Resistor("R2", 1.7, 1.2, 1.7, 1.4, value="10K"))  # collector -> +9V

    # Output cap (1uF electrolytic) -> volume pot
    p.add(RadialElectrolytic("C2", 1.7, 1.4, 2.0, 1.4, value="1uF"))

    # Emitter resistor to ground
    p.add(Resistor("R3", 1.5, 1.5, 1.5, 1.6, value="1K"))

    # Off-board hardware
    p.add(PotentiometerPanel("VR1", x=3.5, y=2.0, resistance="100K", taper="LOG"))
    p.add(MiniToggleSwitch("SW1", x=5.0, y=3.0, switch_type="_3PDT"))
    p.add(PlasticDCJack("J_dc", x=6.5, y=1.0, polarity="CENTER_NEGATIVE"))
    p.add(OpenJack1_4("J_in", x=0.5, y=2.0, type="MONO"))
    p.add(OpenJack1_4("J_out", x=6.5, y=2.5, type="MONO"))

    # A couple of off-board hookup wires showing the topology
    p.add(HookupWire("W_in", points=[(0.5, 2.0), (1.1, 1.4)], color="ff0000"))
    p.add(HookupWire("W_out", points=[(2.0, 1.4), (3.5, 2.0)], color="ffff00"))

    # Labels
    p.add(Label("L_in", x=0.5, y=1.85, text="IN", font_size=11))
    p.add(Label("L_out", x=6.5, y=2.35, text="OUT", font_size=11))
    p.add(Label("L_dc", x=6.5, y=0.85, text="9V", font_size=11))
    p.add(Label("L_vol", x=3.5, y=1.85, text="VOLUME", font_size=11))
    p.add(Label("L_bp", x=5.0, y=2.85, text="BYPASS 3PDT", font_size=10))

    return p


def main() -> None:
    p = build()
    out = p.save("lpb1_stripboard.diy")
    print(f"wrote {out} with {len(p.components)} components")


if __name__ == "__main__":
    main()
