"""Tests for the pydiylc command-line interface.

Covers the in-process API directly plus a few subprocess smoke tests for the
installed entry point.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pydiylc import Project, Resistor, SolderPad, cli


def _make_py(tmp_path: Path) -> Path:
    src = tmp_path / "layout.py"
    src.write_text(
        "from pydiylc import Project, Resistor, SolderPad\n"
        "def build():\n"
        "    p = Project(title='clitest', width_cm=10, height_cm=8)\n"
        "    p.add(SolderPad('P1', x=1.0, y=1.0))\n"
        "    p.add(Resistor('R1', 1.0, 1.0, 1.0, 1.5, value='10K'))\n"
        "    return p\n"
    )
    return src


def test_convert_py_to_diy(tmp_path):
    src = _make_py(tmp_path)
    out = tmp_path / "layout.diy"
    rc = cli.main(["convert", str(src), str(out)])
    assert rc == 0
    assert out.exists()
    ET.parse(out)  # valid XML


def test_convert_py_to_json(tmp_path):
    src = _make_py(tmp_path)
    out = tmp_path / "layout.json"
    rc = cli.main(["convert", str(src), str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["title"] == "clitest"
    assert len(data["components"]) == 2


def test_convert_py_to_svg(tmp_path):
    src = _make_py(tmp_path)
    out = tmp_path / "layout.svg"
    rc = cli.main(["convert", str(src), str(out)])
    assert rc == 0
    text = out.read_text()
    assert "<svg" in text and "</svg>" in text


def test_convert_diy_to_json(tmp_path):
    src = _make_py(tmp_path)
    diy = tmp_path / "layout.diy"
    cli.main(["convert", str(src), str(diy)])
    js = tmp_path / "layout.json"
    rc = cli.main(["convert", str(diy), str(js)])
    assert rc == 0
    data = json.loads(js.read_text())
    assert data["title"] == "clitest"


def test_full_roundtrip_py_diy_json_diy(tmp_path):
    """py -> diy -> json -> diy should preserve component count."""
    src = _make_py(tmp_path)
    a = tmp_path / "a.diy"
    b = tmp_path / "b.json"
    c = tmp_path / "c.diy"
    assert cli.main(["convert", str(src), str(a)]) == 0
    assert cli.main(["convert", str(a), str(b)]) == 0
    assert cli.main(["convert", str(b), str(c)]) == 0
    pa = Project.read(a)
    pc = Project.read(c)
    assert len(pa.components) == len(pc.components)
    for ca, cc in zip(pa.components, pc.components):
        assert type(ca) is type(cc)
        assert ca.name == cc.name


def test_render_default_output_path(tmp_path):
    src = _make_py(tmp_path)
    rc = cli.main(["render", str(src)])
    assert rc == 0
    expected = src.with_suffix(".svg")
    assert expected.exists()


def test_render_with_explicit_out(tmp_path):
    src = _make_py(tmp_path)
    out = tmp_path / "custom.svg"
    rc = cli.main(["render", str(src), "--out", str(out)])
    assert rc == 0
    assert out.exists()


def test_render_rejects_unsupported_output(tmp_path, capsys):
    """render only supports .svg / .png; .jpg etc. is rejected."""
    src = _make_py(tmp_path)
    rc = cli.main(["render", str(src), "--out", str(tmp_path / "x.jpg")])
    assert rc == 2
    err = capsys.readouterr().err
    assert ".svg" in err and ".png" in err


def test_info_prints_summary(tmp_path, capsys):
    src = _make_py(tmp_path)
    rc = cli.main(["info", str(src)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "title:" in out
    assert "clitest" in out
    assert "Resistor" in out


def test_info_shows_warnings_for_unknown_components(tmp_path, capsys):
    """If a .diy contains an unknown component, info should surface a warning."""
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
<project>
  <fileVersion><major>5</major><minor>0</minor><build>0</build></fileVersion>
  <title>w</title>
  <author></author>
  <width value="10.0" unit="cm"/>
  <height value="10.0" unit="cm"/>
  <gridSpacing value="0.1" unit="in"/>
  <components>
    <diylc.foo.NonExistent>
      <name>N1</name>
    </diylc.foo.NonExistent>
  </components>
</project>
"""
    f = tmp_path / "x.diy"
    f.write_text(xml)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rc = cli.main(["info", str(f)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out.lower()


def test_no_command_shows_help(capsys):
    rc = cli.main([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "convert" in out and "render" in out and "info" in out


def test_missing_source_returns_2(tmp_path):
    rc = cli.main(["convert", str(tmp_path / "nope.py"), str(tmp_path / "x.diy")])
    assert rc == 2


def test_unsupported_target_extension(tmp_path):
    src = _make_py(tmp_path)
    rc = cli.main(["convert", str(src), str(tmp_path / "x.xml")])
    assert rc != 0


def test_load_project_main_returning_project(tmp_path):
    """A demo with `main()` returning a Project should be loadable too."""
    src = tmp_path / "demo.py"
    src.write_text(
        "from pydiylc import Project, Resistor\n"
        "def main():\n"
        "    p = Project(title='m')\n"
        "    p.add(Resistor('R1', 0, 0, 0, 0.5))\n"
        "    return p\n"
    )
    p = cli.load_project(src)
    assert p.title == "m"
    assert len(p.components) == 1


# -- subprocess smoke (entry point really resolves) ---------------------------


def test_pydiylc_help_subprocess():
    rc = subprocess.run(
        [sys.executable, "-m", "pydiylc.cli", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 0
    assert "convert" in rc.stdout
    assert "render" in rc.stdout


def test_pydiylc_info_subprocess(tmp_path):
    src = _make_py(tmp_path)
    rc = subprocess.run(
        [sys.executable, "-m", "pydiylc.cli", "info", str(src)],
        capture_output=True, text=True, timeout=10,
    )
    assert rc.returncode == 0
    assert "clitest" in rc.stdout
