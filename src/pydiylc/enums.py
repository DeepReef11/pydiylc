"""Allowed enum values for DIYLC component fields.

This is the single source of truth — runtime validation, docstrings, and the
machine-readable catalog all read from here. Values come from
diy-layout-creator's Java source (org.diylc.components.*) as of DIYLC 5.7.x.
"""

from __future__ import annotations

# Resistor.power
POWER = ("QUARTER", "HALF", "ONE", "TWO")

# Resistor.color_code
RESISTOR_COLOR_CODE = ("NONE", "_4_BAND", "_5_BAND", "_6_BAND")

# Resistor.shape
RESISTOR_SHAPE = ("Standard", "Tubular")

# Capacitor.voltage (also Electrolytic)
VOLTAGE = (
    "_4V", "_6V3", "_10V", "_16V", "_25V", "_35V", "_50V", "_63V",
    "_100V", "_160V", "_200V", "_250V", "_400V", "_450V", "_600V", "_1kV",
)

# Generic display field on most components
DISPLAY = ("NAME", "VALUE", "NONE", "BOTH")

# Resistor / capacitor labelOriantation [sic, upstream typo]
LABEL_ORIENTATION = ("Directional", "Horizontal")

# Board.type for BlankBoard
BOARD_TYPE = ("SQUARE", "ROUND")

# Perfboard coordinate axis types
COORDINATE_AXIS = ("Numbers", "Letters")

# Perfboard coordinateOrigin
COORDINATE_ORIGIN = ("Top_Left", "Top_Right", "Bottom_Left", "Bottom_Right")

# Perfboard coordinateDisplay
COORDINATE_DISPLAY = ("None", "One_Side", "Both_Sides")

# Trace / Jumper / wire style
LINE_STYLE = ("SOLID", "DASHED", "DOTTED")

# HookupWire gauge (AWG)
WIRE_GAUGE = ("_12", "_14", "_16", "_18", "_20", "_22", "_24", "_26", "_28", "_30")

# HookupWire pointCount
WIRE_POINT_COUNT = ("TWO", "THREE", "FOUR", "FIVE", "SEVEN")

# SolderPad.type
PAD_TYPE = ("ROUND", "SQUARE", "OVAL_HORIZONTAL", "OVAL_VERTICAL")

# Board.mode
BOARD_MODE = ("TwoPoints", "Explicit")

# Label alignments
HORIZONTAL_ALIGNMENT = ("LEFT", "CENTER", "RIGHT")
VERTICAL_ALIGNMENT = ("TOP", "CENTER", "BOTTOM")
LABEL_ORIENTATION_4 = ("DEFAULT", "_90", "_180", "_270")

# Measure units recognized on <... unit="X"/>
LENGTH_UNIT = ("mm", "cm", "in", "px")
RESISTANCE_UNIT = ("R", "K", "M", "G")
CAPACITANCE_UNIT = ("pF", "nF", "uF", "mF", "F")
VOLTAGE_UNIT = ("V", "kV", "mV")
CURRENT_UNIT = ("A", "mA", "uA")

# Standard 4-way rotation used by transistors, DIL ICs, pots, labels
ORIENTATION = ("DEFAULT", "_90", "_180", "_270")

# Transistor-specific display field (adds PINOUT)
TRANSISTOR_DISPLAY = ("NAME", "VALUE", "NONE", "BOTH", "PINOUT")

# TransistorTO92 pinout (BJT layouts cover 99% of pedal/amp use cases)
TRANSISTOR_PINOUT = (
    "BJT_EBC", "BJT_CBE", "BJT_BCE", "BJT_ECB",
    "JFET_DSG", "JFET_GSD", "JFET_DGS", "JFET_SGD", "JFET_GDS",
    "MOSFET_DSG", "MOSFET_GSD", "MOSFET_DGS", "MOSFET_SGD", "MOSFET_GDS",
    "REGULATOR_IGO", "REGULATOR_OGI", "REGULATOR_GOI", "REGULATOR_AOI", "REGULATOR_GIO",
)

# DIL IC pin count (4..50 even, written as "_8", "_14", "_16", ...)
DIL_PIN_COUNT = tuple(f"_{n}" for n in range(4, 52, 2))

# DIL IC pin-number display
DIL_DISPLAY_NUMBERS = ("No", "DIP", "Connector", "DIP_MIRROR", "CONNECTOR_MIRROR")

# Potentiometer taper
POT_TAPER = ("LIN", "LOG", "REV_LOG", "W", "S", "M", "N")

# Potentiometer panel type
POT_TYPE = ("ThroughHole", "PCB")

# Potentiometer view orientation
POT_VIEW = ("ShaftDown", "ShaftUp")


def check(field: str, value, allowed: tuple[str, ...]) -> None:
    """Raise ValueError listing allowed values when value isn't permitted."""
    if value not in allowed:
        raise ValueError(
            f"{field}: expected one of {list(allowed)}, got {value!r}"
        )
