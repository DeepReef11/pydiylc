"""Tests for jump-to-target candidate finding (headless)."""

from __future__ import annotations

from pydiylc import Project, PerfBoard, Resistor, SolderPad, CopperTrace
from pydiylc.jump import find_targets, target_for_hint, _direction_ok, _board_holes


def test_direction_cone():
    # right
    assert _direction_ok(1.0, 0.0, "right")
    assert not _direction_ok(-1.0, 0.0, "right")
    # down (y increases downward)
    assert _direction_ok(0.0, 1.0, "down")
    assert not _direction_ok(0.0, -1.0, "down")
    # up
    assert _direction_ok(0.0, -1.0, "up")
    # diagonal within cone of right
    assert _direction_ok(1.0, 0.5, "right")
    # diagonal outside the right cone (mostly down)
    assert not _direction_ok(0.2, 1.0, "right")


def test_board_holes_grid():
    b = PerfBoard("B1", x1=1.0, y1=1.0, x2=1.3, y2=1.2)  # 0.1 in spacing
    holes = _board_holes(b)
    # 4 cols (1.0,1.1,1.2,1.3) x 3 rows (1.0,1.1,1.2) = 12
    assert len(holes) == 12
    assert (1.0, 1.0) in holes
    assert (1.3, 1.2) in holes


def test_find_targets_finds_junction_to_the_right():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))   # our node
    p.add(SolderPad("P2", x=3.0, y=1.0))   # to the right
    p.add(SolderPad("P3", x=1.0, y=3.0))   # below, not right
    # Move P1's only node to the right.
    targets = find_targets(p, 0, 0, "right", include_holes=False)
    xs = {(t.x, t.y) for t in targets}
    assert (3.0, 1.0) in xs
    assert (1.0, 3.0) not in xs  # below is filtered out


def test_targets_sorted_nearest_first():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    p.add(SolderPad("Pclose", x=1.0, y=0.0))
    p.add(SolderPad("Pfar", x=5.0, y=0.0))
    targets = find_targets(p, 0, 0, "right", include_holes=False)
    assert targets[0].distance < targets[1].distance
    assert (targets[0].x, targets[0].y) == (1.0, 0.0)


def test_hints_assigned_homerow_first():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    p.add(SolderPad("P2", x=1.0, y=0.0))
    p.add(SolderPad("P3", x=2.0, y=0.0))
    targets = find_targets(p, 0, 0, "right", include_holes=False)
    assert targets[0].hint == "f"
    assert targets[1].hint == "j"


def test_excludes_own_position():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=2.0, y=1.0))
    targets = find_targets(p, 0, 0, "right", include_holes=False)
    assert all(not (t.x == 1.0 and t.y == 1.0) for t in targets)


def test_holes_included_when_on_perfboard():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=1.5))
    p.add(SolderPad("P1", x=1.0, y=1.2))  # left edge of the board
    targets = find_targets(p, 1, 0, "right", include_holes=True)
    # Should find board holes to the right at y≈1.2.
    holes = [t for t in targets if t.kind == "hole"]
    assert holes
    assert any(abs(t.y - 1.2) < 1e-6 and t.x > 1.0 for t in holes)


def test_holes_excluded_when_flag_off():
    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=1.5))
    p.add(SolderPad("P1", x=1.0, y=1.2))
    targets = find_targets(p, 1, 0, "right", include_holes=False)
    assert all(t.kind != "hole" for t in targets)


def test_max_targets_caps_count():
    p = Project()
    p.add(SolderPad("P0", x=0.0, y=0.0))
    for i in range(1, 10):
        p.add(SolderPad(f"P{i}", x=float(i), y=0.0))
    targets = find_targets(p, 0, 0, "right", include_holes=False, max_targets=3)
    assert len(targets) == 3


def test_target_for_hint_lookup():
    p = Project()
    p.add(SolderPad("P1", x=0.0, y=0.0))
    p.add(SolderPad("P2", x=1.0, y=0.0))
    targets = find_targets(p, 0, 0, "right", include_holes=False)
    t = target_for_hint(targets, "f")
    assert t is not None and (t.x, t.y) == (1.0, 0.0)
    assert target_for_hint(targets, "Z") is None


def test_two_pin_endpoint_jump():
    """Jump a resistor's second endpoint toward another node."""
    p = Project()
    p.add(Resistor("R1", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    p.add(SolderPad("P1", x=3.0, y=1.5))  # to the right of R1's end 2
    targets = find_targets(p, 0, 1, "right", include_holes=False)
    assert any((t.x, t.y) == (3.0, 1.5) for t in targets)


def test_no_targets_in_empty_direction():
    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    p.add(SolderPad("P2", x=3.0, y=1.0))  # only to the right
    targets = find_targets(p, 0, 0, "left", include_holes=False)
    assert targets == []


# ---------------------------------------------------------------------------
# Hole-step arrow nudge
# ---------------------------------------------------------------------------


def test_hole_delta_on_board():
    from pydiylc.jump import hole_delta

    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=1.5))  # 0.1in holes
    # A point on the board nudges by one hole.
    assert hole_delta(p, 1.3, 1.2, "right") == (0.1, 0.0)
    assert hole_delta(p, 1.3, 1.2, "up") == (0.0, -0.1)
    assert hole_delta(p, 1.3, 1.2, "down") == (0.0, 0.1)
    assert hole_delta(p, 1.3, 1.2, "left") == (-0.1, 0.0)


def test_hole_delta_off_board_is_none():
    from pydiylc.jump import hole_delta

    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=1.5))
    assert hole_delta(p, 9.0, 9.0, "right") is None


def test_hole_step_reads_board_spacing():
    from pydiylc.jump import hole_step_for

    p = Project()
    p.add(PerfBoard("B1", x1=1.0, y1=1.0, x2=2.0, y2=1.5))
    assert hole_step_for(p, 1.5, 1.2) == 0.1
    assert hole_step_for(p, 9.0, 9.0) is None


# ---------------------------------------------------------------------------
# Fuzzy go-to search
# ---------------------------------------------------------------------------


def test_searchable_targets_labels():
    from pydiylc.jump import searchable_targets

    p = Project()
    p.add(Resistor("R3", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    p.add(SolderPad("P1", x=2.0, y=2.0))
    targets = searchable_targets(p)
    labels = {t.label for t in targets}
    assert "R3 end 1" in labels
    assert "R3 end 2" in labels
    assert "P1" in labels  # single anchor → bare name


def test_searchable_excludes_self():
    from pydiylc.jump import searchable_targets

    p = Project()
    p.add(Resistor("R3", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    p.add(SolderPad("P1", x=2.0, y=2.0))
    targets = searchable_targets(p, exclude_component=0)
    assert all(t.component_index != 0 for t in targets)


def test_fuzzy_filter_matches_subsequence():
    from pydiylc.jump import searchable_targets, fuzzy_filter

    p = Project()
    p.add(Resistor("R3", x1=1.0, y1=1.0, x2=1.0, y2=1.5))
    p.add(Resistor("R10", x1=2.0, y1=1.0, x2=2.0, y2=1.5))
    targets = searchable_targets(p)
    # "r3end2" should match "R3 end 2" (spaces ignored).
    res = fuzzy_filter(targets, "r3end2")
    assert res and res[0].label == "R3 end 2"


def test_fuzzy_filter_ranks_contiguous_first():
    from pydiylc.jump import SnapTarget, fuzzy_filter

    targets = [
        SnapTarget("Q1 base", 0, 0, 0, 0),
        SnapTarget("BananaBus", 1, 0, 0, 0),
    ]
    res = fuzzy_filter(targets, "base")
    # "base" is contiguous in "Q1 base" → ranked above the scattered match.
    assert res[0].label == "Q1 base"


def test_fuzzy_empty_query_returns_all():
    from pydiylc.jump import searchable_targets, fuzzy_filter

    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    targets = searchable_targets(p)
    assert fuzzy_filter(targets, "") == targets


def test_fuzzy_no_match_returns_empty():
    from pydiylc.jump import searchable_targets, fuzzy_filter

    p = Project()
    p.add(SolderPad("P1", x=1.0, y=1.0))
    targets = searchable_targets(p)
    assert fuzzy_filter(targets, "zzzz") == []
