"""Tiny user-preferences store.

Persists viewer preferences (currently just whether to show the save-diff
dialog) to ``~/.config/pydiylc/prefs.json``. Pure, headless, no GTK.

The store is intentionally small and tolerant: corrupt JSON, missing keys,
unwritable home directory — all degrade gracefully to in-memory defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


_VALID_THEMES = ("light", "dark", "system")


@dataclass
class Prefs:
    """User preferences. Read on viewer start, written when changed."""

    show_save_dialog: bool = True
    show_panel_hint: bool = True
    theme: str = "system"  # "light", "dark", or "system"
    _path: Path | None = None

    @classmethod
    def default_path(cls) -> Path:
        base = os.environ.get("XDG_CONFIG_HOME")
        if base:
            root = Path(base)
        else:
            root = Path.home() / ".config"
        return root / "pydiylc" / "prefs.json"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Prefs":
        p = Path(path) if path is not None else cls.default_path()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        theme = str(data.get("theme", "system"))
        if theme not in _VALID_THEMES:
            theme = "system"
        prefs = cls(
            show_save_dialog=bool(data.get("show_save_dialog", True)),
            show_panel_hint=bool(data.get("show_panel_hint", True)),
            theme=theme,
            _path=p,
        )
        return prefs

    def save(self) -> bool:
        """Persist to ``self._path``. Returns True on success."""
        if self._path is None:
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({
                    "show_save_dialog": self.show_save_dialog,
                    "show_panel_hint": self.show_panel_hint,
                    "theme": self.theme,
                }, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError:
            return False
