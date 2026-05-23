"""Tests for the user-preferences store (headless)."""

from __future__ import annotations

from pydiylc.prefs import Prefs


def test_default_show_save_dialog_true():
    p = Prefs()
    assert p.show_save_dialog is True


def test_load_missing_file_returns_defaults(tmp_path):
    p = Prefs.load(tmp_path / "nope.json")
    assert p.show_save_dialog is True
    assert p._path == tmp_path / "nope.json"


def test_save_and_reload_roundtrip(tmp_path):
    path = tmp_path / "prefs.json"
    p = Prefs.load(path)
    p.show_save_dialog = False
    assert p.save() is True
    p2 = Prefs.load(path)
    assert p2.show_save_dialog is False


def test_save_creates_parent_dir(tmp_path):
    deep = tmp_path / "a" / "b" / "prefs.json"
    p = Prefs.load(deep)
    p.show_save_dialog = False
    assert p.save() is True
    assert deep.exists()


def test_load_corrupt_json_returns_defaults(tmp_path):
    bad = tmp_path / "prefs.json"
    bad.write_text("{not json", encoding="utf-8")
    p = Prefs.load(bad)
    assert p.show_save_dialog is True


def test_load_wrong_shape_returns_defaults(tmp_path):
    bad = tmp_path / "prefs.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")  # JSON array, not object
    p = Prefs.load(bad)
    assert p.show_save_dialog is True


def test_default_path_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    p = Prefs.default_path()
    assert p == tmp_path / "pydiylc" / "prefs.json"


def test_default_path_falls_back_to_dotconfig(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = Prefs.default_path()
    assert p == tmp_path / ".config" / "pydiylc" / "prefs.json"
