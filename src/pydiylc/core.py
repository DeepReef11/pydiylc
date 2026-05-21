from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


# File-format version pydiylc claims to be. Matches DIYLC 5.7.x at time of
# writing. The on-disk schema has been stable since v3 — bumping the major
# would only matter if DIYLC starts gating features on this header.
DEFAULT_FILE_VERSION = (5, 7, 0)


@dataclass(frozen=True)
class Measure:
    """A DIYLC measurement: numeric value plus a unit string ("in", "cm", "mm", ...).

    DIYLC accepts the unit on most attribute-style measure elements,
    e.g. `<width value="0.125" unit="in"/>`.
    """

    value: float
    unit: str = "in"

    def attrs(self) -> str:
        return f'value="{_fmt(self.value)}" unit="{self.unit}"'


def inches(v: float) -> Measure:
    return Measure(v, "in")


def mm(v: float) -> Measure:
    return Measure(v, "mm")


def cm(v: float) -> Measure:
    return Measure(v, "cm")


def _fmt(v: float) -> str:
    # DIYLC writes floats like "1.5", "0.125", "470.0". Avoid scientific
    # notation and trailing precision noise; one decimal place minimum.
    if isinstance(v, int):
        return f"{v}.0"
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


def _hex(color: str | int) -> str:
    """Normalize a color to 6-char lowercase hex (no #)."""
    if isinstance(color, int):
        return f"{color:06x}"
    s = color.lstrip("#").lower()
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or any(c not in "0123456789abcdef" for c in s):
        raise ValueError(f"invalid hex color: {color!r}")
    return s


def _esc(s: str) -> str:
    return escape(s, {'"': "&quot;"})


@dataclass
class Project:
    title: str = "New Project"
    author: str = ""
    width_cm: float = 29.0
    height_cm: float = 21.0
    grid_inches: float = 0.1
    dot_spacing: int = 1
    file_version: tuple[int, int, int] = DEFAULT_FILE_VERSION
    components: list = field(default_factory=list)

    def add(self, component) -> None:
        self.components.append(component)

    def extend(self, items: Iterable) -> None:
        self.components.extend(items)

    def to_xml(self) -> str:
        maj, minr, build = self.file_version
        body = ["\n".join(c.to_xml(indent=4) for c in self.components)]
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            "<project>\n"
            "  <fileVersion>\n"
            f"    <major>{maj}</major>\n"
            f"    <minor>{minr}</minor>\n"
            f"    <build>{build}</build>\n"
            "  </fileVersion>\n"
            f"  <title>{_esc(self.title)}</title>\n"
            f"  <author>{_esc(self.author)}</author>\n"
            f'  <width value="{_fmt(self.width_cm)}" unit="cm"/>\n'
            f'  <height value="{_fmt(self.height_cm)}" unit="cm"/>\n'
            f'  <gridSpacing value="{_fmt(self.grid_inches)}" unit="in"/>\n'
            f"  <dotSpacing>{self.dot_spacing}</dotSpacing>\n"
            "  <components>\n"
            + (body[0] + "\n" if body[0] else "")
            + "  </components>\n"
            "  <groups/>\n"
            "  <lockedLayers/>\n"
            "</project>\n"
        )

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(self.to_xml(), encoding="utf-8")
        return p

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """Build a Project from a dict matching the LLM-facing schema.

        See ``pydiylc.loader`` for the full schema. Convenience wrapper around
        ``pydiylc.project_from_dict``.
        """
        from .loader import project_from_dict

        return project_from_dict(data)

    @classmethod
    def from_json(cls, text: str) -> "Project":
        """Build a Project from a JSON string."""
        from .loader import project_from_json

        return project_from_json(text)

    @classmethod
    def read(cls, path: str | Path) -> "Project":
        """Parse a .diy file into a Project.

        Tolerates unknown component types — they're dropped with a warning
        captured in ``project._read_warnings``. See ``pydiylc.reader`` for
        details.
        """
        from .reader import read_project

        return read_project(path)


def fmt(v: float) -> str:
    """Public re-export of the float formatter — useful for component templates."""
    return _fmt(v)


def hex_color(c: str | int) -> str:
    return _hex(c)


def esc(s: str) -> str:
    return _esc(s)
