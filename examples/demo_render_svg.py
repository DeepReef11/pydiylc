"""Demo: render the LPB-1 stripboard layout to an SVG you can open in any browser.

Produces lpb1.svg in the current directory.
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
from pydiylc.svg import render_svg_file, RenderOptions


def main() -> None:
    p = Project(title="LPB-1", width_cm=18, height_cm=10)
    p.add(VeroBoard("Board1", 1.0, 1.0, 2.2, 1.7, orientation="HORIZONTAL"))
    p.add(TraceCut("Cut1", x=1.5, y=1.3, orientation="HORIZONTAL"))
    p.add(TraceCut("Cut2", x=1.7, y=1.3, orientation="HORIZONTAL"))
    p.add(TraceCut("Cut3", x=1.5, y=1.5, orientation="HORIZONTAL"))

    p.add(TransistorTO92("Q1", x=1.6, y=1.3, value="2N5088"))
    p.add(SolderPad("PadIn", x=1.1, y=1.4))
    p.add(RadialFilmCapacitor("C1", 1.1, 1.4, 1.4, 1.4, value="100nF"))
    p.add(Resistor("R1", 1.5, 1.4, 1.5, 1.6, value="1M"))
    p.add(Resistor("R2", 1.7, 1.2, 1.7, 1.4, value="10K"))
    p.add(RadialElectrolytic("C2", 1.7, 1.4, 2.0, 1.4, value="1uF"))
    p.add(Resistor("R3", 1.5, 1.5, 1.5, 1.6, value="1K"))

    p.add(PotentiometerPanel("VR1", x=3.5, y=2.0, resistance="100K", taper="LOG"))
    p.add(MiniToggleSwitch("SW1", x=5.0, y=3.0, switch_type="_3PDT"))
    p.add(PlasticDCJack("J_dc", x=6.5, y=1.0))
    p.add(OpenJack1_4("J_in", x=0.5, y=2.0))
    p.add(OpenJack1_4("J_out", x=6.5, y=2.5))

    p.add(HookupWire("W_in", points=[(0.5, 2.0), (1.1, 1.4)], color="ff0000"))
    p.add(HookupWire("W_out", points=[(2.0, 1.4), (3.5, 2.0)], color="ffff00"))

    p.add(Label("L_in", x=0.5, y=1.85, text="IN", font_size=11))
    p.add(Label("L_out", x=6.5, y=2.35, text="OUT", font_size=11))
    p.add(Label("L_vol", x=3.5, y=1.85, text="VOLUME", font_size=11))
    p.add(Label("L_bp", x=5.0, y=2.85, text="BYPASS 3PDT", font_size=10))

    render_svg_file(p, "lpb1.svg")
    # also a higher-res version
    from pydiylc.svg import render_svg
    from pathlib import Path

    Path("lpb1_hires.svg").write_text(
        render_svg(p, RenderOptions(px_per_inch=192))
    )

    print("wrote lpb1.svg and lpb1_hires.svg")
    print("open either in a browser, or convert to PNG with `rsvg-convert lpb1.svg -o lpb1.png`")


if __name__ == "__main__":
    main()
