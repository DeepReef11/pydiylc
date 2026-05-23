import pytest

from pydiylc import (
    Resistor,
    RadialFilmCapacitor,
    RadialElectrolytic,
    Jumper,
    HookupWire,
    SolderPad,
    Label,
    CopperTrace,
    PerfBoard,
    BlankBoard,
)


def test_resistor_rejects_bad_power():
    with pytest.raises(ValueError, match="Resistor.power"):
        Resistor("R1", 0, 0, 0, 0.5, value="1K", power="half")  # must be HALF


def test_resistor_error_lists_allowed():
    with pytest.raises(ValueError) as ei:
        Resistor("R1", 0, 0, 0, 0.5, value="1K", power="HUGE")
    msg = str(ei.value)
    assert "QUARTER" in msg and "HALF" in msg and "TWO" in msg


def test_capacitor_rejects_bad_voltage():
    with pytest.raises(ValueError, match="voltage"):
        RadialFilmCapacitor("C1", 0, 0, 0, 0.1, value="100nF", voltage="63V")  # must be _63V


def test_jumper_rejects_bad_style():
    with pytest.raises(ValueError, match="style"):
        Jumper("J1", 0, 0, 0, 0.5, style="solid")


def test_hookup_wire_rejects_bad_gauge():
    with pytest.raises(ValueError, match="gauge"):
        HookupWire("W1", points=[(0, 0), (1, 0)], gauge="22")


def test_hookup_wire_accepts_3_points():
    """v3 community files emit wires with 2, 3, 4, 5, or 7 points (the full
    WIRE_POINT_COUNT enum). Reject only < 2."""
    HookupWire("W1", points=[(0, 0), (1, 0), (2, 0)])  # 3 points OK
    HookupWire("W2", points=[(0, 0), (1, 0)])           # 2 OK
    with pytest.raises(ValueError, match="at least 2 points"):
        HookupWire("W3", points=[(0, 0)])               # 1 fails


def test_solder_pad_rejects_bad_type():
    with pytest.raises(ValueError, match="SolderPad.type"):
        SolderPad("P1", x=0, y=0, type="round")


def test_label_rejects_bad_font_style():
    with pytest.raises(ValueError, match="font_style"):
        Label("L1", x=0, y=0, text="x", font_style=7)


def test_label_rejects_bad_alignment():
    with pytest.raises(ValueError, match="horizontal_alignment"):
        Label("L1", x=0, y=0, text="x", horizontal_alignment="middle")


def test_copper_trace_rejects_single_point():
    with pytest.raises(ValueError, match="2 points"):
        CopperTrace("T1", points=[(0, 0)])


def test_perfboard_rejects_bad_origin():
    with pytest.raises(ValueError, match="coordinate_origin"):
        PerfBoard("B", 0, 0, 1, 1, coordinate_origin="topleft")


def test_blank_board_rejects_bad_type():
    with pytest.raises(ValueError, match="BlankBoard.type"):
        BlankBoard("B", 0, 0, 1, 1, type="round")


def test_electrolytic_bad_voltage():
    with pytest.raises(ValueError, match="voltage"):
        RadialElectrolytic("C1", 0, 0, 0, 0.1, value="22uF", voltage="25V")


def test_valid_components_construct():
    # Smoke: every default should be valid.
    Resistor("R1", 0, 0, 0, 0.5)
    RadialFilmCapacitor("C1", 0, 0, 0, 0.1)
    RadialElectrolytic("C1", 0, 0, 0, 0.1)
    Jumper("J1", 0, 0, 0, 0.5)
    HookupWire("W1", points=[(0, 0), (1, 0)])
    SolderPad("P1", x=0, y=0)
    Label("L1", x=0, y=0, text="x")
    CopperTrace("T1", points=[(0, 0), (1, 0)])
    PerfBoard("B", 0, 0, 1, 1)
    BlankBoard("B", 0, 0, 1, 1)
