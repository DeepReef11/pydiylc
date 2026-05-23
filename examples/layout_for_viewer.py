"""Example layout that the viewer can load.

Run::

    pydiylc-view examples/layout_for_viewer.py

The viewer watches this file's mtime and reloads when you save. Try
changing a resistor value or coordinate and saving — the canvas updates.

Conventions the viewer accepts (any one of these is fine):

- Define a top-level ``project`` variable, OR
- Define ``def build() -> Project``.
"""
from pydiylc import Project, VeroBoard, TraceCut, Resistor, RadialFilmCapacitor, RadialElectrolytic, TransistorTO92, PotentiometerPanel, MiniToggleSwitch, PlasticDCJack, OpenJack1_4, SolderPad, HookupWire, Label, BlankBoard, BOM, CopperTrace

def build() -> Project:
    p = Project(title='LPB-1 (viewer)', width_cm=18, height_cm=10)
    p.add(VeroBoard(name='Board1', x1=1.0, y1=1.0, x2=2.2, y2=1.7, orientation='HORIZONTAL'))
    p.add(TraceCut(name='Cut1', x=1.5, y=1.3, orientation='HORIZONTAL'))
    p.add(TraceCut(name='Cut2', x=1.7, y=1.3, orientation='HORIZONTAL'))
    p.add(TransistorTO92(name='Q1', x=1.6, y=1.3, value='2N5088'))
    p.add(SolderPad(name='PadIn', x=3.3, y=0.7))
    p.add(RadialFilmCapacitor(name='C1', x1=1.1, y1=1.4, x2=1.4, y2=1.4, value='100nF'))
    p.add(Resistor(name='R1', x1=1.5, y1=1.4, x2=1.5, y2=1.6, value='1M'))
    p.add(Resistor(name='R2', x1=1.7, y1=1.2, x2=1.7, y2=1.4, value='10K'))
    p.add(RadialElectrolytic(name='C2', x1=1.7, y1=1.4, x2=2.0, y2=1.4, value='1uF'))
    p.add(PotentiometerPanel(name='VR1', x=3.5, y=2.0, resistance='100K', taper='LOG'))
    p.add(MiniToggleSwitch(name='SW1', x=4.2, y=2.9, switch_type='_3PDT'))
    p.add(PlasticDCJack(name='J_dc', x=4.4, y=1.1))
    p.add(OpenJack1_4(name='J_in', x=0.5, y=2.0))
    p.add(OpenJack1_4(name='J_out', x=6.5, y=2.5))
    p.add(HookupWire(name='W_in', points=[(0.5, 2.0), (1.1, 1.4)], color='ff0000'))
    p.add(HookupWire(name='W_out', points=[(2.0, 1.4), (3.5, 2.0)], color='ffff00'))
    p.add(Label(name='L_in', x=0.5, y=1.85, text='IN', font_size=11))
    p.add(Label(name='L_out', x=6.5, y=2.35, text='OUT', font_size=11))
    p.add(Label(name='L_vol', x=3.5, y=1.85, text='VOLUME', font_size=11))
    p.add(BlankBoard(name='BlankBoard1', x1=1.8, y1=3.5, x2=1.9, y2=3.4))
    p.add(BOM(name='BOM1', x=2.4, y=3.4))
    p.add(CopperTrace(name='CopperTrace1', points=[(4.3, 2.0), (5.3, 2.0)]))
    p.add(CopperTrace(name='CopperTrace2', points=[(4.8, 2.3), (5.8, 2.3)]))
    return p
project = build()
