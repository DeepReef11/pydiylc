"""Tests for the pydiylc MCP server.

These work whether the MCP SDK is installed or not. When MCP is missing,
they verify graceful ImportError messages; when present, they verify the
server constructs and exposes the expected tools.
"""

from __future__ import annotations

import pytest

from pydiylc import mcp_server


def test_has_mcp_returns_bool():
    assert isinstance(mcp_server.has_mcp(), bool)


@pytest.mark.skipif(not mcp_server.has_mcp(), reason="MCP SDK not installed")
def test_build_server_runs_without_error():
    server = mcp_server.build_server()
    assert server.name == "pydiylc"


@pytest.mark.skipif(not mcp_server.has_mcp(), reason="MCP SDK not installed")
def test_server_lists_expected_tools():
    """Every documented tool should be registered."""
    import asyncio

    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    expected = {
        # Catalog & reference
        "list_component_types", "enum_values", "describe_component_type",
        "list_categories", "list_components_in_category", "list_enums",
        # Project lifecycle
        "create_project", "create_project_from_dict", "list_projects",
        "delete_project", "set_project_metadata",
        # Inspection
        "list_components", "get_component", "find_components", "get_pins",
        "stats",
        # Edits
        "add_component", "add_components", "remove_component",
        "move_component", "move_node", "move_node_to",
        "rotate_component", "duplicate_component",
        "set_value", "set_field", "set_fields", "add_wire", "connect",
        "snap_to_grid", "align",
        # Validation + history
        "validate", "undo", "redo", "history",
        # I/O
        "save", "render_svg", "render_png", "to_json", "read_diy",
    }
    missing = expected - names
    assert not missing, f"missing MCP tools: {missing}"


@pytest.mark.skipif(not mcp_server.has_mcp(), reason="MCP SDK not installed")
def test_server_exposes_resources():
    """catalog and llms.txt should be available as MCP resources."""
    import asyncio

    server = mcp_server.build_server()
    resources = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "pydiylc://catalog" in uris
    assert "pydiylc://llms.txt" in uris


@pytest.mark.skipif(not mcp_server.has_mcp(), reason="MCP SDK not installed")
def test_server_exposes_prompts():
    """Four canned workflow prompts."""
    import asyncio

    server = mcp_server.build_server()
    prompts = asyncio.run(server.list_prompts())
    names = {p.name for p in prompts}
    assert "build_pedal_layout" in names
    assert "modify_existing_layout" in names
    assert "build_guitar_wiring" in names
    assert "build_amp_psu" in names


@pytest.mark.skipif(not mcp_server.has_mcp(), reason="MCP SDK not installed")
def test_main_without_mcp_returns_2(monkeypatch):
    """`pydiylc-mcp main()` should return 2 when SDK is missing."""

    def fake_require():
        raise ImportError("simulated missing MCP")

    monkeypatch.setattr(mcp_server, "_require_mcp", fake_require)
    assert mcp_server.main([]) == 2


def test_project_store_isolated_between_calls():
    """The in-memory store should track multiple projects independently."""
    from pydiylc.core import Project

    mcp_server._PROJECTS.clear()
    mcp_server._PROJECTS["a"] = Project(title="A")
    mcp_server._PROJECTS["b"] = Project(title="B")
    assert mcp_server._get("a").title == "A"
    assert mcp_server._get("b").title == "B"
    with pytest.raises(KeyError, match="create_project first"):
        mcp_server._get("nope")


# ---------------------------------------------------------------------------
# End-to-end tool invocation (calls the actual handlers)
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_fixture():
    """Fresh server + clean project store per test."""
    if not mcp_server.has_mcp():
        pytest.skip("MCP SDK not installed")
    mcp_server._PROJECTS.clear()
    server = mcp_server.build_server()
    return server


def _call(server, name: str, args: dict):
    """Invoke a tool by name and return the canonical Python result.

    FastMCP returns ``(content_list, structured_dict)``. The structured
    payload is always under the ``"result"`` key when the tool returned a
    Python value, so that's the canonical shape we hand back. Older SDK
    versions that emit only a content list fall through to the JSON-parse
    of the first text element.
    """
    import asyncio
    import json

    raw = asyncio.run(server.call_tool(name, args))
    if isinstance(raw, tuple):
        content, structured = raw
    else:
        content, structured = raw, None
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    # Fall back to concatenated text content as JSON.
    if not content:
        return None
    if len(content) == 1 and hasattr(content[0], "text"):
        try:
            return json.loads(content[0].text)
        except (ValueError, TypeError):
            return content[0].text
    # Multiple text items → a list whose elements are each JSON.
    out = []
    for item in content:
        if hasattr(item, "text"):
            try:
                out.append(json.loads(item.text))
            except (ValueError, TypeError):
                out.append(item.text)
    return out


def test_create_project_via_tool(mcp_fixture):
    out = _call(mcp_fixture, "create_project", {
        "project_id": "p1", "title": "Test", "width_cm": 10, "height_cm": 8,
    })
    assert out["project_id"] == "p1"
    assert out["title"] == "Test"
    assert out["components"] == 0
    assert "p1" in mcp_server._PROJECTS


def test_full_session_via_tools(mcp_fixture):
    """Multi-step session: create → add → move → rotate → set_value → save."""
    import tempfile, os
    _call(mcp_fixture, "create_project", {"project_id": "s"})
    # Add a Resistor and a SolderPad.
    _call(mcp_fixture, "add_component", {
        "project_id": "s",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5,
                      "value": "10K"},
    })
    _call(mcp_fixture, "add_component", {
        "project_id": "s",
        "component": {"type": "SolderPad", "name": "P1", "x": 2.0, "y": 2.0},
    })
    # Move R1 by (0.5, 0).
    moved = _call(mcp_fixture, "move_component",
                  {"project_id": "s", "name": "R1", "dx": 0.5, "dy": 0.0})
    assert moved["x1"] == 1.5 and moved["x2"] == 1.5
    # set_value: 10K -> 47K
    _call(mcp_fixture, "set_value",
          {"project_id": "s", "name": "R1", "value": "47K"})
    # Duplicate -> R2.
    dup = _call(mcp_fixture, "duplicate_component",
                {"project_id": "s", "name": "R1"})
    assert dup["name"] == "R2"
    # list_components has 3 entries now.
    listed = _call(mcp_fixture, "list_components", {"project_id": "s"})
    assert len(listed) == 3
    # Save to a tmp .diy
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.diy")
        out = _call(mcp_fixture, "save", {"project_id": "s", "path": path})
        assert os.path.exists(out["path"])


def test_find_components_via_tool(mcp_fixture):
    """find_components fuzzy-matches by name."""
    _call(mcp_fixture, "create_project", {"project_id": "f"})
    _call(mcp_fixture, "add_component", {"project_id": "f",
        "component": {"type": "Resistor", "name": "R3",
                      "x1": 0, "y1": 0, "x2": 0, "y2": 0.5}})
    _call(mcp_fixture, "add_component", {"project_id": "f",
        "component": {"type": "Resistor", "name": "R10",
                      "x1": 1, "y1": 0, "x2": 1, "y2": 0.5}})
    res = _call(mcp_fixture, "find_components",
                {"project_id": "f", "query": "r3"})
    assert res
    assert res[0]["name"] == "R3"


def test_enum_values_via_tool(mcp_fixture):
    res = _call(mcp_fixture, "enum_values", {"enum_name": "POWER"})
    assert "HALF" in res
    assert "QUARTER" in res


def test_describe_component_type_via_tool(mcp_fixture):
    res = _call(mcp_fixture, "describe_component_type",
                {"type_name": "Resistor"})
    assert res["python_class"] == "Resistor"
    assert res["diylc_class"] == "diylc.passive.Resistor"


def test_rotate_component_via_tool(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "rot"})
    _call(mcp_fixture, "add_component", {"project_id": "rot",
        "component": {"type": "TransistorTO92", "name": "Q1",
                      "x": 2.0, "y": 2.0, "orientation": "DEFAULT"}})
    res = _call(mcp_fixture, "rotate_component",
                {"project_id": "rot", "name": "Q1"})
    # Orientation enum cycled to the next value.
    assert res["orientation"] == "_90"


def test_set_project_metadata_via_tool(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "m"})
    res = _call(mcp_fixture, "set_project_metadata",
                {"project_id": "m", "title": "Renamed", "width_cm": 20})
    assert res["title"] == "Renamed"
    assert res["width_cm"] == 20.0


def test_list_and_delete_project_via_tool(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "x"})
    _call(mcp_fixture, "create_project", {"project_id": "y"})
    listed = _call(mcp_fixture, "list_projects", {})
    pids = {p["project_id"] for p in listed}
    assert {"x", "y"} <= pids
    res = _call(mcp_fixture, "delete_project", {"project_id": "x"})
    assert res["deleted"] is True
    res2 = _call(mcp_fixture, "delete_project", {"project_id": "nope"})
    assert res2["deleted"] is False


def test_to_json_round_trips_through_create_from_dict(mcp_fixture):
    """to_json → create_project_from_dict yields an equivalent project."""
    _call(mcp_fixture, "create_project", {"project_id": "a"})
    _call(mcp_fixture, "add_component", {"project_id": "a",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    payload = _call(mcp_fixture, "to_json", {"project_id": "a"})
    _call(mcp_fixture, "create_project_from_dict",
          {"project_id": "b", "payload": payload})
    listed = _call(mcp_fixture, "list_components", {"project_id": "b"})
    assert len(listed) == 1
    assert listed[0]["name"] == "P1"


def test_add_wire_via_tool(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "w"})
    out = _call(mcp_fixture, "add_wire",
                {"project_id": "w", "src": [0.0, 0.0], "dst": [1.0, 0.0]})
    assert out["type"] == "HookupWire"
    assert out["points"][0] == [0.0, 0.0]
    assert out["points"][1] == [1.0, 0.0]


def test_render_svg_via_tool(mcp_fixture, tmp_path):
    _call(mcp_fixture, "create_project", {"project_id": "r"})
    _call(mcp_fixture, "add_component", {"project_id": "r",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    out = _call(mcp_fixture, "render_svg",
                {"project_id": "r", "path": str(tmp_path / "x.svg")})
    assert (tmp_path / "x.svg").exists()
    assert "<svg" in (tmp_path / "x.svg").read_text()


def test_catalog_resource_returns_json(mcp_fixture):
    """The pydiylc://catalog resource should return parseable JSON."""
    import asyncio
    import json

    contents = asyncio.run(mcp_fixture.read_resource("pydiylc://catalog"))
    # FastMCP wraps the return in iterable content; collapse to text.
    if hasattr(contents, "__iter__") and not isinstance(contents, str):
        text = "".join(c.content for c in contents if hasattr(c, "content"))
    else:
        text = str(contents)
    data = json.loads(text)
    assert "components" in data
    assert any(c["python_class"] == "Resistor" for c in data["components"])


def test_unknown_component_via_tool_raises(mcp_fixture):
    """A bad arg raises ToolError; the message mentions the offender."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="Nope"):
        asyncio.run(
            mcp_fixture.call_tool("describe_component_type", {"type_name": "Nope"})
        )


# ---------------------------------------------------------------------------
# Polish: batch add, connect, get_pins, validate, set_field, undo/redo,
# inline content returns, "did you mean" hints.
# ---------------------------------------------------------------------------


def test_add_components_batch(mcp_fixture):
    """add_components accepts many items in one call."""
    _call(mcp_fixture, "create_project", {"project_id": "b"})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "b",
        "components": [
            {"type": "Resistor", "name": f"R{i}",
             "x1": 1.0, "y1": float(i), "x2": 1.0, "y2": i + 0.3,
             "value": "10K"}
            for i in range(5)
        ],
    })
    assert res["added"] == 5
    assert res["errors"] == []
    assert res["aborted"] is False
    listed = _call(mcp_fixture, "list_components", {"project_id": "b"})
    assert len(listed) == 5


def test_add_components_records_errors_not_raise(mcp_fixture):
    """Bad items in a batch produce errors but don't fail the batch."""
    _call(mcp_fixture, "create_project", {"project_id": "b2"})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "b2",
        "components": [
            {"type": "Resistor", "name": "R1",
             "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5, "value": "10K"},
            {"type": "Bogus", "name": "B1"},
            {"type": "SolderPad", "name": "P1", "x": 2.0, "y": 2.0},
        ],
    })
    assert res["added"] == 2
    assert len(res["errors"]) == 1
    assert res["errors"][0]["type"] == "Bogus"


def test_add_components_stop_on_error(mcp_fixture):
    """stop_on_error=True aborts on first bad item, leaves project clean."""
    _call(mcp_fixture, "create_project", {"project_id": "b3"})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "b3",
        "stop_on_error": True,
        "components": [
            {"type": "Resistor", "name": "R1",
             "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5, "value": "10K"},
            {"type": "Bogus", "name": "B1"},
            {"type": "SolderPad", "name": "P1", "x": 2.0, "y": 2.0},
        ],
    })
    assert res["added"] == 0
    assert res["aborted"] is True
    listed = _call(mcp_fixture, "list_components", {"project_id": "b3"})
    assert len(listed) == 0  # nothing committed


def test_get_pins_multi_pin_schematic_symbols(mcp_fixture):
    """Schematic-symbol components (tubes, transformers, op-amps, rectifiers,
    etc.) must surface every control point through get_pins().

    Regression for the round where the AMP-schematic stress test found
    that TriodeSymbol et al. were reporting only 1 pin instead of their
    actual 5+ pins, making pin-by-pin wiring impossible. The fix was to
    promote the inline pts list to a _control_points() method on each
    affected class so graph.control_points_of() picks it up.
    """
    _call(mcp_fixture, "create_project", {"project_id": "pins"})
    _call(mcp_fixture, "add_components", {
        "project_id": "pins",
        "components": [
            {"type": "TriodeSymbol", "name": "V1", "x": 1, "y": 1,
             "value": "12AX7"},
            {"type": "PentodeSymbol", "name": "V2", "x": 3, "y": 1,
             "value": "EL84"},
            {"type": "TubeDiodeSymbol", "name": "V3", "x": 5, "y": 1,
             "value": "5Y3"},
            {"type": "AudioTransformer", "name": "T1", "x": 7, "y": 1},
            {"type": "JFETSymbol", "name": "Q1", "x": 9, "y": 1},
            {"type": "BridgeRectifier", "name": "BR1", "x": 1, "y": 3},
            {"type": "ICSymbol", "name": "U1", "x": 3, "y": 3,
             "ic_point_count": "_5"},
            {"type": "RotarySelectorSwitch", "name": "S1", "x": 5, "y": 3,
             "position_count": "FIVE"},
            {"type": "MiniRelay", "name": "K1", "x": 7, "y": 3},
            {"_type": "LeverSwitch", "name": "SW1", "x": 9, "y": 3,
             "type": "DPDT"},
        ],
    })
    expected_pin_counts = {
        "V1": 5,    # TriodeSymbol
        "V2": 7,    # PentodeSymbol
        "V3": 5,    # TubeDiodeSymbol
        "T1": 6,    # AudioTransformer (3 primary + 3 secondary)
        "Q1": 3,    # JFET (gate, source, drain)
        "BR1": 4,   # BridgeRectifier (+, ~, ~, -)
        "U1": 5,    # ICSymbol _5 (2 inputs + output + V+ + V-)
        "S1": 6,    # rotary FIVE: rotor + 5 positions
        "K1": 8,    # MiniRelay 4×2
        "SW1": 4,   # LeverSwitch DPDT = 4 lugs
    }
    for name, expected in expected_pin_counts.items():
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": "pins", "name": name})
        assert len(pins) == expected, (
            f"{name}: expected {expected} pins, got {len(pins)}: {pins}"
        )


def test_get_pins(mcp_fixture):
    """get_pins surfaces control-point coordinates by index."""
    _call(mcp_fixture, "create_project", {"project_id": "g"})
    _call(mcp_fixture, "add_component", {"project_id": "g",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    pins = _call(mcp_fixture, "get_pins", {"project_id": "g", "name": "R1"})
    assert len(pins) == 2
    assert pins[0]["pin"] == 0
    assert pins[0]["x"] == 1.0


def test_connect_by_name_picks_nearest_pins(mcp_fixture):
    """connect with no pin indices picks the closest pair automatically."""
    _call(mcp_fixture, "create_project", {"project_id": "c"})
    _call(mcp_fixture, "add_component", {"project_id": "c",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    _call(mcp_fixture, "add_component", {"project_id": "c",
        "component": {"type": "Resistor", "name": "R2",
                      "x1": 1.0, "y1": 2.0, "x2": 1.0, "y2": 2.5}})
    res = _call(mcp_fixture, "connect", {
        "project_id": "c", "from_name": "R1", "to_name": "R2",
    })
    # R1's bottom pin (1.0, 1.5) is closest to R2's top pin (1.0, 2.0).
    assert res["from"]["pin"] == 1
    assert res["to"]["pin"] == 0
    assert res["type"] == "HookupWire"


def test_connect_explicit_pins(mcp_fixture):
    """connect with explicit from_pin / to_pin uses those endpoints."""
    _call(mcp_fixture, "create_project", {"project_id": "c2"})
    _call(mcp_fixture, "add_component", {"project_id": "c2",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    _call(mcp_fixture, "add_component", {"project_id": "c2",
        "component": {"type": "Resistor", "name": "R2",
                      "x1": 2.0, "y1": 1.0, "x2": 2.0, "y2": 1.5}})
    res = _call(mcp_fixture, "connect", {
        "project_id": "c2", "from_name": "R1", "to_name": "R2",
        "from_pin": 0, "to_pin": 0,
    })
    assert res["from"]["pin"] == 0
    assert res["to"]["pin"] == 0


def test_connect_kind_trace(mcp_fixture):
    """kind='trace' adds a CopperTrace instead of a HookupWire."""
    _call(mcp_fixture, "create_project", {"project_id": "c3"})
    _call(mcp_fixture, "add_component", {"project_id": "c3",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "c3",
        "component": {"type": "SolderPad", "name": "P2", "x": 2.0, "y": 1.0}})
    res = _call(mcp_fixture, "connect", {
        "project_id": "c3", "from_name": "P1", "to_name": "P2", "kind": "trace",
    })
    assert res["type"] == "CopperTrace"


def test_set_field_general(mcp_fixture):
    """set_field can change arbitrary attributes, with type coercion."""
    _call(mcp_fixture, "create_project", {"project_id": "f"})
    _call(mcp_fixture, "add_component", {"project_id": "f",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    res = _call(mcp_fixture, "set_field", {
        "project_id": "f", "name": "R1", "field": "alpha", "value": 64,
    })
    assert res["type"] == "Resistor"
    # Verify the change committed.
    got = _call(mcp_fixture, "get_component", {"project_id": "f", "name": "R1"})
    assert got["alpha"] == 64


def test_set_field_dry_run(mcp_fixture):
    """dry_run=True reports the would-be change without committing."""
    _call(mcp_fixture, "create_project", {"project_id": "fd"})
    _call(mcp_fixture, "add_component", {"project_id": "fd",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    res = _call(mcp_fixture, "set_field", {
        "project_id": "fd", "name": "R1", "field": "alpha", "value": 64,
        "dry_run": True,
    })
    assert res["dry_run"] is True
    # Original value unchanged.
    got = _call(mcp_fixture, "get_component", {"project_id": "fd", "name": "R1"})
    assert got["alpha"] == 127  # unchanged from the default


def test_set_field_unknown_field_suggests(mcp_fixture):
    """Bad field name produces a 'did you mean' hint."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    _call(mcp_fixture, "create_project", {"project_id": "fs"})
    _call(mcp_fixture, "add_component", {"project_id": "fs",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1.0, "y1": 1.0, "x2": 1.0, "y2": 1.5}})
    with pytest.raises(ToolError, match="alpha|valid fields"):
        asyncio.run(mcp_fixture.call_tool("set_field", {
            "project_id": "fs", "name": "R1", "field": "alpah",  # typo
            "value": 64,
        }))


def test_validate_detects_duplicate_names(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "v"})
    _call(mcp_fixture, "add_component", {"project_id": "v",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5}})
    _call(mcp_fixture, "add_component", {"project_id": "v",
        "component": {"type": "Resistor", "name": "R1",  # duplicate
                      "x1": 2, "y1": 1, "x2": 2, "y2": 1.5}})
    rep = _call(mcp_fixture, "validate", {"project_id": "v"})
    assert rep["ok"] is False
    dup = [i for i in rep["issues"] if i["kind"] == "duplicate_name"]
    assert dup
    assert dup[0]["name"] == "R1"


def test_validate_detects_off_canvas(mcp_fixture):
    """Off-canvas geometry is surfaced as an INFO, not an error.

    Real DIYLC layouts routinely place off-board hardware (jacks, pots,
    labels) outside the canvas bounds — about half the upstream corpus
    does this. Flagging it as an error would make validate untrustworthy.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "v2", "width_cm": 5.0, "height_cm": 5.0})
    _call(mcp_fixture, "add_component", {"project_id": "v2",
        "component": {"type": "SolderPad", "name": "P1", "x": 100.0, "y": 100.0}})
    rep = _call(mcp_fixture, "validate", {"project_id": "v2"})
    off = [i for i in rep["issues"] if i["kind"] == "off_canvas"]
    assert off
    assert off[0]["name"] == "P1"
    # Off-canvas must be severity=info so ok stays True for layouts that
    # deliberately place off-board hardware outside the strict canvas.
    assert off[0]["severity"] == "info"
    assert rep["ok"] is True  # off-canvas alone doesn't break validate
    assert rep["infos"]       # but the info is surfaced
    assert not rep["errors"]


def test_validate_duplicate_names_are_errors(mcp_fixture):
    """Duplicate names DO break ok — they corrupt the AST-edit path."""
    _call(mcp_fixture, "create_project", {"project_id": "vd"})
    _call(mcp_fixture, "add_component", {"project_id": "vd",
        "component": {"type": "SolderPad", "name": "P1", "x": 1, "y": 1}})
    _call(mcp_fixture, "add_component", {"project_id": "vd",
        "component": {"type": "SolderPad", "name": "P1", "x": 2, "y": 2}})
    rep = _call(mcp_fixture, "validate", {"project_id": "vd"})
    assert rep["ok"] is False
    assert rep["errors"]
    assert rep["errors"][0]["kind"] == "duplicate_name"
    assert rep["errors"][0]["severity"] == "error"


def test_validate_clean_project(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "v3"})
    _call(mcp_fixture, "add_component", {"project_id": "v3",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    rep = _call(mcp_fixture, "validate", {"project_id": "v3"})
    assert rep["ok"] is True
    assert rep["issues"] == []


def test_undo_redo_round_trip(mcp_fixture):
    """add → undo restores; redo reapplies."""
    _call(mcp_fixture, "create_project", {"project_id": "u"})
    _call(mcp_fixture, "add_component", {"project_id": "u",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    res = _call(mcp_fixture, "undo", {"project_id": "u"})
    assert res["undone"] is True
    assert res["components"] == 0
    res2 = _call(mcp_fixture, "redo", {"project_id": "u"})
    assert res2["redone"] is True
    assert res2["components"] == 1


def test_history_status(mcp_fixture):
    """history reports depth + last label."""
    _call(mcp_fixture, "create_project", {"project_id": "h"})
    _call(mcp_fixture, "add_component", {"project_id": "h",
        "component": {"type": "SolderPad", "name": "P1", "x": 1, "y": 1}})
    _call(mcp_fixture, "move_component",
          {"project_id": "h", "name": "P1", "dx": 0.5, "dy": 0})
    res = _call(mcp_fixture, "history", {"project_id": "h"})
    assert res["depth"] == 2
    assert res["can_undo"] is True
    assert "move" in (res["last_label"] or "")


def test_render_svg_inline_content(mcp_fixture):
    """render_svg without a path returns SVG markup inline."""
    _call(mcp_fixture, "create_project", {"project_id": "r"})
    _call(mcp_fixture, "add_component", {"project_id": "r",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    res = _call(mcp_fixture, "render_svg",
                {"project_id": "r", "return_content": True})
    assert "content" in res
    assert "<svg" in res["content"]


def test_save_inline_content(mcp_fixture):
    """save with return_content=True returns the .diy XML inline."""
    _call(mcp_fixture, "create_project", {"project_id": "s"})
    _call(mcp_fixture, "add_component", {"project_id": "s",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    res = _call(mcp_fixture, "save",
                {"project_id": "s", "return_content": True})
    assert "content" in res
    assert "<project>" in res["content"]
    assert "P1" in res["content"]


def test_missing_component_suggests_close_match(mcp_fixture):
    """Mistyped name gets a 'did you mean' hint in the error."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    _call(mcp_fixture, "create_project", {"project_id": "m"})
    _call(mcp_fixture, "add_component", {"project_id": "m",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5}})
    with pytest.raises(ToolError, match="R1"):
        # 'r1' (lowercase) is one edit away from 'R1'.
        asyncio.run(mcp_fixture.call_tool("get_component",
                                          {"project_id": "m", "name": "r1"}))


def test_missing_project_suggests_close_match(mcp_fixture):
    """Mistyped project id also gets a hint."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    _call(mcp_fixture, "create_project", {"project_id": "alpha"})
    with pytest.raises(ToolError, match="alpha"):
        asyncio.run(mcp_fixture.call_tool("list_components",
                                          {"project_id": "alpa"}))


def test_type_collision_error_is_actionable(mcp_fixture):
    """When a 'type' field collides with the class discriminator, the error
    must mention the offending name and show the _type fix.

    Concrete trap: an LLM writes
        {"type": "OpenJack1_4", "name": "J1", "type": "MONO"}
    intending OpenJack1_4 as the class — but Python/JSON keep only the last
    'type', so the class name is silently dropped. The error message has
    to be actionable enough that the LLM can self-correct.
    """
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    _call(mcp_fixture, "create_project", {"project_id": "tc"})
    # Simulate what an LLM-written JSON would parse to in Python:
    bad = {"type": "MONO", "name": "J1", "x": 1.0, "y": 1.0}
    with pytest.raises(ToolError) as ei:
        asyncio.run(mcp_fixture.call_tool("add_component", {
            "project_id": "tc", "component": bad,
        }))
    msg = str(ei.value)
    # Must reference: the bad type value, the component name, and the _type fix.
    assert "MONO" in msg
    assert "J1" in msg
    assert "_type" in msg


def test_type_collision_fixed_with_underscore_type(mcp_fixture):
    """The _type form succeeds where the colliding form fails."""
    _call(mcp_fixture, "create_project", {"project_id": "tc2"})
    res = _call(mcp_fixture, "add_component", {
        "project_id": "tc2",
        "component": {"_type": "OpenJack1_4", "name": "J1",
                      "x": 1.0, "y": 1.0, "type": "MONO"},
    })
    assert res["type"] == "OpenJack1_4"
    assert res["name"] == "J1"


def test_add_component_dry_run(mcp_fixture):
    """dry_run validates without adding."""
    _call(mcp_fixture, "create_project", {"project_id": "dr"})
    res = _call(mcp_fixture, "add_component", {
        "project_id": "dr",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5},
        "dry_run": True,
    })
    assert res["dry_run"] is True
    listed = _call(mcp_fixture, "list_components", {"project_id": "dr"})
    assert len(listed) == 0


# ---------------------------------------------------------------------------
# Catalog browsing (categories, enums) — discovery without fetching the full
# catalog.
# ---------------------------------------------------------------------------


def test_list_categories(mcp_fixture):
    """list_categories returns category names + counts derived from the
    DIYLC class path (diylc.passive.Resistor → 'passive')."""
    res = _call(mcp_fixture, "list_categories", {})
    by_cat = {e["category"]: e["count"] for e in res}
    # 'passive' is huge (resistors, caps, transformers, etc.); 'boards' is
    # smaller. Both must be present.
    assert "passive" in by_cat
    assert "boards" in by_cat
    assert by_cat["passive"] > by_cat["boards"]


def test_list_components_in_category(mcp_fixture):
    """list_components_in_category filters the catalog by slug."""
    res = _call(mcp_fixture, "list_components_in_category",
                {"category": "boards"})
    names = {e["python_class"] for e in res}
    assert "PerfBoard" in names
    assert "VeroBoard" in names
    # Each entry has a short doc.
    for entry in res:
        assert "doc_first_line" in entry


def test_list_components_in_category_unknown_suggests(mcp_fixture):
    """Bad category name gets a 'did you mean' hint."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="boards|passive"):
        asyncio.run(mcp_fixture.call_tool(
            "list_components_in_category", {"category": "boarsd"}  # typo
        ))


def test_list_enums(mcp_fixture):
    """list_enums returns every enum the catalog references."""
    res = _call(mcp_fixture, "list_enums", {})
    names = {e["name"] for e in res}
    # A representative spread of known enums.
    assert "POWER" in names
    assert "VOLTAGE" in names
    assert "ORIENTATION" in names
    # Every entry has a positive count.
    for e in res:
        assert e["count"] > 0


def test_describe_component_type_unknown_suggests(mcp_fixture):
    """Unknown type gets a 'did you mean' hint (vs the old generic 'not found')."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    # 'Resitor' is one edit away from 'Resistor'.
    with pytest.raises(ToolError, match="Resistor"):
        asyncio.run(mcp_fixture.call_tool(
            "describe_component_type", {"type_name": "Resitor"}
        ))


# ---------------------------------------------------------------------------
# Multi-field setter + align + snap_to_grid + stats.
# ---------------------------------------------------------------------------


def test_set_fields_multi(mcp_fixture):
    """set_fields applies multiple field updates atomically."""
    _call(mcp_fixture, "create_project", {"project_id": "sf"})
    _call(mcp_fixture, "add_component", {"project_id": "sf",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5}})
    res = _call(mcp_fixture, "set_fields", {
        "project_id": "sf", "name": "R1",
        "fields": {"alpha": 64, "value": "47K", "color_code": "_4_BAND"},
    })
    assert res["type"] == "Resistor"
    got = _call(mcp_fixture, "get_component",
                {"project_id": "sf", "name": "R1"})
    assert got["alpha"] == 64
    assert got["value"] == "47K"
    assert got["color_code"] == "_4_BAND"


def test_set_fields_atomic_on_failure(mcp_fixture):
    """A bad enum in the batch reverts every field — no partial commit."""
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError

    _call(mcp_fixture, "create_project", {"project_id": "sfa"})
    _call(mcp_fixture, "add_component", {"project_id": "sfa",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5}})
    with pytest.raises(ToolError):
        asyncio.run(mcp_fixture.call_tool("set_fields", {
            "project_id": "sfa", "name": "R1",
            "fields": {"alpha": 64, "color_code": "NOT_A_VALID_ENUM"},
        }))
    # alpha must NOT have changed since the whole batch was supposed to fail.
    got = _call(mcp_fixture, "get_component",
                {"project_id": "sfa", "name": "R1"})
    assert got["alpha"] == 127  # default, not 64


def test_set_fields_dry_run(mcp_fixture):
    """dry_run reports the diff per-field without committing."""
    _call(mcp_fixture, "create_project", {"project_id": "sfd"})
    _call(mcp_fixture, "add_component", {"project_id": "sfd",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 1, "y1": 1, "x2": 1, "y2": 1.5}})
    res = _call(mcp_fixture, "set_fields", {
        "project_id": "sfd", "name": "R1",
        "fields": {"alpha": 64, "value": "47K"},
        "dry_run": True,
    })
    assert res["dry_run"] is True
    assert res["changes"]["alpha"]["to"] == 64
    assert res["changes"]["value"]["to"] == "47K"
    # Confirm nothing committed.
    got = _call(mcp_fixture, "get_component",
                {"project_id": "sfd", "name": "R1"})
    assert got["alpha"] == 127


def test_snap_to_grid_whole_project(mcp_fixture):
    """snap_to_grid without a name snaps every off-grid coord."""
    _call(mcp_fixture, "create_project", {"project_id": "sg"})
    _call(mcp_fixture, "add_component", {"project_id": "sg",
        "component": {"type": "SolderPad", "name": "P1",
                      "x": 1.2345, "y": 1.7891}})
    res = _call(mcp_fixture, "snap_to_grid", {"project_id": "sg"})
    assert res["snapped"] >= 1
    got = _call(mcp_fixture, "get_component", {"project_id": "sg", "name": "P1"})
    assert got["x"] == pytest.approx(1.2, abs=1e-6)
    assert got["y"] == pytest.approx(1.8, abs=1e-6)


def test_snap_to_grid_single_component(mcp_fixture):
    """snap_to_grid with a name only touches that component."""
    _call(mcp_fixture, "create_project", {"project_id": "sg2"})
    _call(mcp_fixture, "add_component", {"project_id": "sg2",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.234, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "sg2",
        "component": {"type": "SolderPad", "name": "P2", "x": 2.567, "y": 2.0}})
    _call(mcp_fixture, "snap_to_grid", {"project_id": "sg2", "name": "P1"})
    p1 = _call(mcp_fixture, "get_component", {"project_id": "sg2", "name": "P1"})
    p2 = _call(mcp_fixture, "get_component", {"project_id": "sg2", "name": "P2"})
    assert p1["x"] == pytest.approx(1.2, abs=1e-6)
    assert p2["x"] == 2.567  # untouched


def test_snap_to_grid_dry_run(mcp_fixture):
    """dry_run reports proposed snaps without committing."""
    _call(mcp_fixture, "create_project", {"project_id": "sgd"})
    _call(mcp_fixture, "add_component", {"project_id": "sgd",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.234, "y": 1.0}})
    res = _call(mcp_fixture, "snap_to_grid",
                {"project_id": "sgd", "dry_run": True})
    assert res["dry_run"] is True
    assert res["snaps"] >= 1
    got = _call(mcp_fixture, "get_component", {"project_id": "sgd", "name": "P1"})
    assert got["x"] == 1.234  # unchanged


def test_align_x_first(mcp_fixture):
    """align axis=x mode=first lines components up to the first's x."""
    _call(mcp_fixture, "create_project", {"project_id": "al"})
    _call(mcp_fixture, "add_component", {"project_id": "al",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "al",
        "component": {"type": "SolderPad", "name": "P2", "x": 1.5, "y": 2.0}})
    _call(mcp_fixture, "add_component", {"project_id": "al",
        "component": {"type": "SolderPad", "name": "P3", "x": 2.0, "y": 3.0}})
    res = _call(mcp_fixture, "align", {
        "project_id": "al",
        "names": ["P1", "P2", "P3"],
        "axis": "x", "mode": "first",
    })
    assert res["aligned"] == 2
    p2 = _call(mcp_fixture, "get_component", {"project_id": "al", "name": "P2"})
    p3 = _call(mcp_fixture, "get_component", {"project_id": "al", "name": "P3"})
    assert p2["x"] == pytest.approx(1.0)
    assert p3["x"] == pytest.approx(1.0)
    # Y values preserved (we only aligned on x).
    assert p2["y"] == pytest.approx(2.0)


def test_align_y_mean(mcp_fixture):
    """align axis=y mode=mean centers on the average y."""
    _call(mcp_fixture, "create_project", {"project_id": "al2"})
    _call(mcp_fixture, "add_component", {"project_id": "al2",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "al2",
        "component": {"type": "SolderPad", "name": "P2", "x": 2.0, "y": 3.0}})
    _call(mcp_fixture, "align", {
        "project_id": "al2", "names": ["P1", "P2"],
        "axis": "y", "mode": "mean",
    })
    p1 = _call(mcp_fixture, "get_component", {"project_id": "al2", "name": "P1"})
    p2 = _call(mcp_fixture, "get_component", {"project_id": "al2", "name": "P2"})
    assert p1["y"] == pytest.approx(2.0)
    assert p2["y"] == pytest.approx(2.0)


def test_align_dry_run(mcp_fixture):
    _call(mcp_fixture, "create_project", {"project_id": "ald"})
    _call(mcp_fixture, "add_component", {"project_id": "ald",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "ald",
        "component": {"type": "SolderPad", "name": "P2", "x": 2.0, "y": 1.0}})
    res = _call(mcp_fixture, "align", {
        "project_id": "ald", "names": ["P1", "P2"],
        "axis": "x", "mode": "first", "dry_run": True,
    })
    assert res["dry_run"] is True
    assert res["anchor"] == 1.0
    # No commit.
    p2 = _call(mcp_fixture, "get_component", {"project_id": "ald", "name": "P2"})
    assert p2["x"] == 2.0


def test_end_to_end_pedal_build(mcp_fixture, tmp_path):
    """Real-world stress test: build a complete pedal layout through MCP
    tool calls only, then save → re-read and check it round-trips.

    This is what an LLM client does. Catches regressions that unit tests
    don't see — e.g. the type-vs-_type collision on jack components, or
    the connect() failing to find a neighbor — by running the full
    documented "build from scratch" pattern from LLMS.txt end to end.
    """
    project_id = "e2e"

    # 1. discover (would-be cheap exploration on the LLM side).
    cats = _call(mcp_fixture, "list_categories", {})
    assert any(c["category"] == "passive" for c in cats)

    # 2. create.
    _call(mcp_fixture, "create_project", {
        "project_id": project_id, "title": "E2E test",
        "width_cm": 18, "height_cm": 12,
    })

    # 3. batch-add a 23-component LPB-1-shaped layout.
    components = [
        {"type": "VeroBoard", "name": "Board1",
         "x1": 1.0, "y1": 1.0, "x2": 2.2, "y2": 1.7,
         "orientation": "HORIZONTAL"},
        {"type": "TraceCut", "name": "Cut1", "x": 1.5, "y": 1.3,
         "orientation": "HORIZONTAL"},
        {"type": "TransistorTO92", "name": "Q1",
         "x": 1.6, "y": 1.3, "value": "2N5088", "pinout": "BJT_EBC"},
        {"type": "SolderPad", "name": "PadIn", "x": 1.1, "y": 1.4},
        {"type": "RadialFilmCapacitor", "name": "C1",
         "x1": 1.1, "y1": 1.4, "x2": 1.4, "y2": 1.4, "value": "100nF"},
        {"type": "Resistor", "name": "R1",
         "x1": 1.5, "y1": 1.4, "x2": 1.5, "y2": 1.6, "value": "1M"},
        {"type": "Resistor", "name": "R2",
         "x1": 1.7, "y1": 1.2, "x2": 1.7, "y2": 1.4, "value": "10K"},
        {"type": "RadialElectrolytic", "name": "C2",
         "x1": 1.7, "y1": 1.4, "x2": 2.0, "y2": 1.4, "value": "1uF"},
        {"type": "PotentiometerPanel", "name": "VR1",
         "x": 3.5, "y": 2.0, "resistance": "100K", "taper": "LOG"},
        {"type": "MiniToggleSwitch", "name": "SW1",
         "x": 5.0, "y": 3.0, "switch_type": "_3PDT"},
        # The _type-discriminator trick — these would silently drop the
        # class name with plain "type" (regression coverage for that).
        {"_type": "OpenJack1_4", "name": "J_in",
         "x": 0.5, "y": 2.0, "type": "MONO"},
        {"_type": "OpenJack1_4", "name": "J_out",
         "x": 6.5, "y": 2.5, "type": "MONO"},
        {"type": "PlasticDCJack", "name": "J_dc",
         "x": 6.5, "y": 1.0, "polarity": "CENTER_NEGATIVE"},
    ]
    res = _call(mcp_fixture, "add_components", {
        "project_id": project_id, "components": components,
    })
    assert res["added"] == len(components)
    assert res["errors"] == []

    # 4. connect by name — verifies the auto-nearest-pin path works on a
    # heterogeneous mix (a single-anchor SolderPad to a single-anchor jack,
    # then a two-pin cap to a single-anchor pot).
    c1 = _call(mcp_fixture, "connect", {
        "project_id": project_id,
        "from_name": "J_in", "to_name": "PadIn",
    })
    assert c1["type"] == "HookupWire"
    c2 = _call(mcp_fixture, "connect", {
        "project_id": project_id,
        "from_name": "C2", "to_name": "VR1",
    })
    assert c2["type"] == "HookupWire"

    # 5. validate — must come back clean for a well-formed layout.
    rep = _call(mcp_fixture, "validate", {"project_id": project_id})
    assert rep["ok"], f"validate found issues: {rep['issues']}"

    # 6. stats — sanity check counts.
    st = _call(mcp_fixture, "stats", {"project_id": project_id})
    by_type = {e["type"]: e["count"] for e in st["by_type"]}
    assert by_type["Resistor"] == 2
    assert by_type["OpenJack1_4"] == 2
    assert by_type["HookupWire"] == 2  # the two connects

    # 7. inline render — sandboxed-chat flow.
    svg = _call(mcp_fixture, "render_svg", {
        "project_id": project_id, "return_content": True,
    })
    assert "<svg" in svg["content"]

    # 8. save to disk and re-read — round-trip check.
    out = tmp_path / "pedal.diy"
    _call(mcp_fixture, "save", {
        "project_id": project_id, "path": str(out),
    })
    assert out.exists()
    reread = _call(mcp_fixture, "read_diy", {
        "project_id": f"{project_id}_rt", "path": str(out),
    })
    assert reread["components"] == st["components"]
    assert reread["warnings"] == []


def test_end_to_end_tube_amp_schematic(mcp_fixture, tmp_path):
    """Second real-world stress test: build a tube-amp schematic.

    Complements test_end_to_end_pedal_build by exercising the schematic
    side: multi-pin tube symbols, audio transformer, ground references.
    Found three real bugs the first time it ran (GroundSymbol type-
    collision, missing _control_points on TriodeSymbol/PentodeSymbol/
    AudioTransformer, connect() silently picking the same pin every
    time). All fixed; this test locks them down.
    """
    project_id = "amp"
    _call(mcp_fixture, "create_project", {
        "project_id": project_id, "title": "Champ schematic",
        "width_cm": 36, "height_cm": 22,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": project_id,
        "components": [
            {"_type": "TriodeSymbol", "name": "V1a",
             "x": 3.0, "y": 2.0, "value": "12AX7"},
            {"_type": "PentodeSymbol", "name": "V2",
             "x": 7.0, "y": 2.0, "value": "6V6"},
            {"type": "AudioTransformer", "name": "T1",
             "x": 9.0, "y": 1.5, "value": "Champ OT"},
            {"type": "ResistorSymbol", "name": "R1",
             "x1": 3.5, "y1": 1.5, "x2": 3.5, "y2": 0.5, "value": "100K"},
            # Both type collisions in one go — GroundSymbol uses the
            # discriminator trick the doc warns about.
            {"_type": "GroundSymbol", "name": "G1",
             "x": 1.5, "y": 3.2, "type": "DEFAULT"},
            {"_type": "GroundSymbol", "name": "G2",
             "x": 7.3, "y": 3.2, "type": "TRIANGLE"},
        ],
    })
    assert res["added"] == 6
    assert res["errors"] == []

    # Multi-pin schematic symbols expose every pin (bug regression).
    pins = {
        "V1a": 5,   # TriodeSymbol: grid, plate, cathode, 2 heaters
        "V2":  7,   # PentodeSymbol
        "T1":  6,   # AudioTransformer: 3 primary + 3 secondary
    }
    for name, want in pins.items():
        got = _call(mcp_fixture, "get_pins",
                    {"project_id": project_id, "name": name})
        assert len(got) == want, (
            f"{name}: expected {want} pins, got {len(got)}: {got}"
        )

    # Wire signal path — exercises connect()'s nearest-pin heuristic
    # across single-anchor (GroundSymbol) and multi-pin (TriodeSymbol).
    _call(mcp_fixture, "connect", {
        "project_id": project_id,
        "from_name": "V1a", "to_name": "T1",
    })

    rep = _call(mcp_fixture, "validate", {"project_id": project_id})
    assert rep["ok"], f"validate found issues: {rep['issues']}"

    # Round-trip through disk.
    out = tmp_path / "amp.diy"
    _call(mcp_fixture, "save", {
        "project_id": project_id, "path": str(out),
    })
    reread = _call(mcp_fixture, "read_diy", {
        "project_id": f"{project_id}_rt", "path": str(out),
    })
    assert reread["components"] == 7   # 6 added + 1 wire
    assert reread["warnings"] == []


def test_end_to_end_big_muff_high_density(mcp_fixture, tmp_path):
    """Third real-world stress test: a 50-component Big Muff fuzz pedal.

    Probes scale and density: four transistors with feedback loops,
    diode clipping pairs (back-to-back), tone stack, three pots,
    3PDT switch, jacks, DC inlet, multiple ground references. Sibling
    to test_end_to_end_pedal_build (stripboard) and
    test_end_to_end_tube_amp_schematic (schematic).

    Specifically catches:
    - Density: 20+ wires placed via connect() — does nearest-pin still
      pick sensible pairs at scale?
    - The off-canvas false-positive: this layout puts pots/jacks/labels
      outside the strict canvas (DIYLC convention for off-board hardware),
      which should be surfaced as info, not error.
    - High batch sizes: 50+ components in one add_components call.
    """
    project_id = "muff"
    _call(mcp_fixture, "create_project", {
        "project_id": project_id, "title": "Big Muff Pi",
        "width_cm": 18, "height_cm": 14,
    })
    # Trimmed-down version that hits the same stress points.
    components = [
        {"type": "VeroBoard", "name": "Board1",
         "x1": 0.5, "y1": 0.5, "x2": 4.5, "y2": 2.0,
         "orientation": "HORIZONTAL"},
        # 4 transistors with similar surrounding networks
        *[d for q in range(1, 5) for d in [
            {"type": "TransistorTO92", "name": f"Q{q}",
             "x": 0.6 + q * 0.7, "y": 1.0,
             "value": "2N5088", "pinout": "BJT_EBC"},
            {"type": "Resistor", "name": f"R_C{q}",
             "x1": 0.6 + q * 0.7, "y1": 0.7,
             "x2": 0.6 + q * 0.7, "y2": 0.5, "value": "10K"},
            {"type": "Resistor", "name": f"R_E{q}",
             "x1": 0.6 + q * 0.7, "y1": 1.3,
             "x2": 0.6 + q * 0.7, "y2": 1.5, "value": "2K2"},
        ]],
        # 3 pots in a row off-board (intentionally outside canvas)
        *[{"type": "PotentiometerPanel", "name": f"VR{i}",
           "x": 8.0, "y": 0.5 + i * 1.5,
           "resistance": "100K", "taper": "LIN"} for i in range(1, 4)],
        # Jacks (off-board, hence outside canvas)
        {"_type": "OpenJack1_4", "name": "J_in",
         "x": 0.5, "y": 6.0, "type": "MONO"},
        {"_type": "OpenJack1_4", "name": "J_out",
         "x": 8.0, "y": 6.0, "type": "MONO"},
    ]
    res = _call(mcp_fixture, "add_components", {
        "project_id": project_id, "components": components,
    })
    assert res["errors"] == [], f"batch errors: {res['errors']}"

    # ~10 wires — exercises connect's nearest-pin heuristic at density.
    for src, dst in [
        ("J_in", "Q1"), ("Q1", "Q2"), ("Q2", "Q3"), ("Q3", "Q4"),
        ("Q4", "VR3"), ("VR3", "J_out"),
        ("VR1", "Q2"),  # feedback loop
    ]:
        _call(mcp_fixture, "connect", {
            "project_id": project_id, "from_name": src, "to_name": dst,
        })

    rep = _call(mcp_fixture, "validate", {"project_id": project_id})
    # Off-board hardware lives outside the canvas; validate.ok should
    # stay True (info-severity only), and infos should be reported.
    assert rep["ok"], (
        f"validate must accept off-board hardware as info-only, "
        f"but reported errors: {rep['errors']}"
    )
    assert rep["infos"], "off-canvas hardware should produce info entries"
    # Every off-canvas issue must be severity=info.
    for issue in rep["issues"]:
        if issue["kind"] == "off_canvas":
            assert issue["severity"] == "info"

    # Round-trip through disk at this size.
    out = tmp_path / "muff.diy"
    _call(mcp_fixture, "save", {"project_id": project_id, "path": str(out)})
    reread = _call(mcp_fixture, "read_diy", {
        "project_id": f"{project_id}_rt", "path": str(out),
    })
    assert reread["components"] == rep["components"]
    assert reread["warnings"] == []


def test_end_to_end_two_stage_amp_with_feedback(mcp_fixture, tmp_path):
    """Fourth real-world stress test: two-stage triode preamp with
    overall negative feedback from V2 plate back into the V1 cathode
    network. Sibling to the LPB-1, Champ, and Big Muff tests.

    Specifically catches:
    - Typo'd class names ('RadialCeramicCapacitor' for
      RadialCeramicDiskCapacitor) must surface a 'Did you mean?'
      suggestion, not a misleading key-collision hint.
    - Shape mismatch ('x'/'y' on a two-point class, or vice versa)
      must say which fields the class actually accepts.
    - connect()'s nearest-pin heuristic stays non-trivial when the
      same node is hit from multiple sides (feedback): pin pairs must
      vary, not collapse to (0, 0).
    """
    pid = "fbamp"
    _call(mcp_fixture, "create_project", {
        "project_id": pid, "title": "Two-stage with feedback",
        "width_cm": 30, "height_cm": 20,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": pid,
        "components": [
            {"_type": "TriodeSymbol", "name": "V1",
             "x": 4.0, "y": 6.0, "value": "12AX7-A"},
            {"_type": "TriodeSymbol", "name": "V2",
             "x": 10.0, "y": 6.0, "value": "12AX7-B"},
            {"type": "AudioTransformer", "name": "OT",
             "x": 16.0, "y": 5.0, "value": "OT-mini"},
            {"type": "ResistorSymbol", "name": "Rp1",
             "x1": 4.3, "y1": 5.7, "x2": 4.3, "y2": 4.0, "value": "100K"},
            {"type": "ResistorSymbol", "name": "Rp2",
             "x1": 10.3, "y1": 5.7, "x2": 10.3, "y2": 4.0, "value": "100K"},
            {"type": "ResistorSymbol", "name": "Rk1",
             "x1": 4.2, "y1": 6.3, "x2": 4.2, "y2": 8.0, "value": "1K5"},
            {"type": "ResistorSymbol", "name": "Rk2",
             "x1": 10.2, "y1": 6.3, "x2": 10.2, "y2": 8.0, "value": "1K5"},
            {"type": "ResistorSymbol", "name": "Rg1",
             "x1": 4.0, "y1": 6.0, "x2": 2.0, "y2": 6.0, "value": "1M"},
            {"type": "ResistorSymbol", "name": "Rg2",
             "x1": 10.0, "y1": 6.0, "x2": 8.0, "y2": 6.0, "value": "470K"},
            {"type": "RadialCeramicDiskCapacitor", "name": "C1",
             "x1": 6.5, "y1": 5.7, "x2": 7.5, "y2": 5.7, "value": "22nF"},
            {"type": "RadialCeramicDiskCapacitor", "name": "C2",
             "x1": 12.5, "y1": 5.7, "x2": 13.5, "y2": 5.7, "value": "22nF"},
            {"type": "ResistorSymbol", "name": "Rfb",
             "x1": 10.3, "y1": 4.0, "x2": 4.2, "y2": 8.5, "value": "47K"},
            {"_type": "GroundSymbol", "name": "G_in",
             "x": 4.2, "y": 9.0, "type": "DEFAULT"},
            {"_type": "GroundSymbol", "name": "G_out",
             "x": 10.2, "y": 9.0, "type": "TRIANGLE"},
            {"_type": "OpenJack1_4", "name": "J_in",
             "x": 0.5, "y": 6.0, "type": "MONO"},
            {"_type": "OpenJack1_4", "name": "J_out",
             "x": 22.0, "y": 5.0, "type": "MONO"},
        ],
    })
    assert res["errors"] == [], f"batch errors: {res['errors']}"
    assert res["added"] == 16

    # Wire chain that revisits V1 from below via the feedback resistor.
    wires = [
        ("J_in", "Rg1"), ("Rg1", "V1"),
        ("V1", "Rp1"), ("V1", "Rk1"), ("Rk1", "G_in"),
        ("V1", "C1"), ("C1", "Rg2"), ("Rg2", "V2"),
        ("V2", "Rp2"), ("V2", "Rk2"), ("Rk2", "G_out"),
        ("V2", "C2"), ("C2", "OT"), ("OT", "J_out"),
        # The feedback path — overall NFB from V2 plate to V1 cathode.
        ("Rp2", "Rfb"), ("Rfb", "Rk1"),
    ]
    used = []
    for src, dst in wires:
        r = _call(mcp_fixture, "connect", {
            "project_id": pid, "from_name": src, "to_name": dst,
        })
        used.append((r["from"]["pin"], r["to"]["pin"]))

    # The nearest-pin heuristic must produce non-trivial choices.
    # If everything collapsed to (0, 0), the bug from the Champ stress
    # test has regressed.
    non_zero = [p for p in used if p != (0, 0)]
    assert len(non_zero) >= len(wires) // 2, (
        f"connect() collapsed to pin (0,0) on most wires: {used}"
    )

    rep = _call(mcp_fixture, "validate", {"project_id": pid})
    assert rep["ok"], f"validate errors: {rep['errors']}"

    out = tmp_path / "fbamp.diy"
    _call(mcp_fixture, "save", {"project_id": pid, "path": str(out)})
    rr = _call(mcp_fixture, "read_diy", {
        "project_id": f"{pid}_rt", "path": str(out),
    })
    assert rr["warnings"] == []
    assert rr["components"] == 16 + len(wires)


def test_typo_in_class_name_suggests_correct_name(mcp_fixture):
    """Typo'd class names should get a 'Did you mean?' hint, not a
    misleading 'key collision' message. Regression test for an LLM
    typing 'RadialCeramicCapacitor' when the real class is named
    RadialCeramicDiskCapacitor.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "t", "width_cm": 10, "height_cm": 8})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "t",
        "components": [{"type": "RadialCeramicCapacitor", "name": "C1",
                        "x1": 1.0, "y1": 1.0, "x2": 2.0, "y2": 1.0}],
    })
    assert res["added"] == 0
    assert len(res["errors"]) == 1
    err = res["errors"][0]["error"]
    assert "Did you mean" in err
    assert "RadialCeramicDiskCapacitor" in err


def test_wrong_coord_shape_lists_accepted_fields(mcp_fixture):
    """If an LLM passes x/y on a two-point component (or vice versa),
    the error must say which fields the class actually accepts. Plain
    'unexpected keyword argument x' is not actionable.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "t", "width_cm": 10, "height_cm": 8})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "t",
        "components": [{"type": "RadialCeramicDiskCapacitor", "name": "C1",
                        "x": 1.0, "y": 1.0}],
    })
    assert res["added"] == 0
    err = res["errors"][0]["error"]
    assert "two-point component" in err
    assert "x1/y1/x2/y2" in err
    # And the full field list must be present for cases where shape
    # isn't the issue (e.g. a misspelled field name).
    assert "Accepted fields" in err


def test_end_to_end_two_channel_amp_with_switching(mcp_fixture, tmp_path):
    """Fifth real-world stress test: two-channel amp with bypass and
    channel switching. Sibling to the LPB-1, Champ, Big Muff, and
    feedback-amp tests.

    Specifically catches a class of regressions where single-anchor
    components with multi-pin layouts report only 1 pin via get_pins
    because their pts list is inline in to_xml() instead of in
    _control_points(). 21 components were affected before this round —
    every jack class, several transistor packages, multi-section
    capacitors, pickups, etc. The assertions below pin the pin count
    of one representative from each family.
    """
    pid = "two_ch"
    _call(mcp_fixture, "create_project", {
        "project_id": pid, "title": "Two-channel amp",
        "width_cm": 40, "height_cm": 25,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": pid,
        "components": [
            # STEREO jack has the auto-grounding switched contact.
            {"_type": "ClosedJack1_4", "name": "J_in",
             "x": 0.5, "y": 5.0, "type": "STEREO"},
            {"_type": "CliffJack1_4", "name": "J_out",
             "x": 30.0, "y": 5.0, "type": "MONO"},
            {"_type": "TriodeSymbol", "name": "V1_clean",
             "x": 5.0, "y": 5.0, "value": "12AX7"},
            {"_type": "TriodeSymbol", "name": "V1_lead",
             "x": 5.0, "y": 12.0, "value": "12AX7"},
            {"_type": "PentodeSymbol", "name": "V2",
             "x": 20.0, "y": 8.0, "value": "EL84"},
            {"_type": "MiniToggleSwitch", "name": "SW_bypass",
             "x": 35.0, "y": 1.0, "switch_type": "_3PDT"},
            {"_type": "LeverSwitch", "name": "SW_chan",
             "x": 35.0, "y": 10.0, "type": "DP3T"},
            {"_type": "MiniRelay", "name": "K1",
             "x": 15.0, "y": 15.0, "value": "12V"},
            {"_type": "GroundSymbol", "name": "G1",
             "x": 5.0, "y": 22.0, "type": "DEFAULT"},
            {"_type": "GroundSymbol", "name": "G2",
             "x": 20.0, "y": 22.0, "type": "TRIANGLE"},
        ],
    })
    assert res["errors"] == []
    assert res["added"] == 10

    # Lock in the pin counts that were silently broken before the
    # _control_points refactor.
    expected_pins = {
        "J_in":      3,   # ClosedJack1_4 STEREO: tip, sleeve, ring
        "J_out":     5,   # CliffJack1_4
        "V1_clean":  5,   # TriodeSymbol
        "V2":        7,   # PentodeSymbol
        "SW_bypass": 9,   # 3PDT toggle
        "SW_chan":   8,   # DP3T lever switch
        "K1":        8,   # MiniRelay
    }
    for name, want in expected_pins.items():
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": pid, "name": name})
        assert len(pins) == want, (
            f"{name}: expected {want} pins, got {len(pins)}"
        )

    # Wire a representative subset — exercises connect across multi-pin
    # components that the bug would have broken.
    for src, dst in [
        ("J_in", "V1_clean"),
        ("V1_clean", "SW_chan"),
        ("V1_lead", "SW_chan"),
        ("SW_chan", "V2"),
        ("V2", "J_out"),
        ("J_in", "G1"),     # auto-ground via the switched ring
        ("V2", "G2"),
    ]:
        _call(mcp_fixture, "connect", {
            "project_id": pid, "from_name": src, "to_name": dst,
        })

    rep = _call(mcp_fixture, "validate", {"project_id": pid})
    assert rep["ok"], f"validate errors: {rep['errors']}"

    out = tmp_path / "twoch.diy"
    _call(mcp_fixture, "save", {"project_id": pid, "path": str(out)})
    rr = _call(mcp_fixture, "read_diy", {
        "project_id": f"{pid}_rt", "path": str(out),
    })
    assert rr["warnings"] == []
    assert rr["components"] == 10 + 7  # components + wires


def test_end_to_end_strat_guitar_wiring(mcp_fixture, tmp_path):
    """Sixth real-world stress test: Stratocaster-style guitar wiring.
    Sibling to the LPB-1, Champ, Big Muff, feedback-amp, and
    two-channel-amp tests.

    Probes a domain (guitar wiring) the prior tests never reached:
    - Single-anchor pickups (SingleCoilPickup has just 1 control point)
      connecting outward through nearby SolderPads.
    - LeverSwitch in its DP3T_5pos form (10 lugs — the original
      Strat 5-way selector).
    - Three pots in a row with a tone cap.
    - render_svg(return_content=True) returns SVG markup under both
      'content' (generic) and 'svg' (descriptive) keys so a caller
      guessing either gets the payload.
    """
    pid = "strat"
    _call(mcp_fixture, "create_project", {
        "project_id": pid, "title": "Strat-style wiring",
        "width_cm": 30, "height_cm": 20,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": pid,
        "components": [
            {"_type": "SingleCoilPickup", "name": "PU_neck",
             "x": 2.0, "y": 4.0, "type": "Stratocaster"},
            {"_type": "SingleCoilPickup", "name": "PU_mid",
             "x": 2.0, "y": 8.0, "type": "Stratocaster"},
            {"_type": "SingleCoilPickup", "name": "PU_bridge",
             "x": 2.0, "y": 12.0, "type": "Stratocaster"},

            # Pickup terminations
            {"type": "SolderPad", "name": "Pad_neck_hot",
             "x": 3.0, "y": 3.5},
            {"type": "SolderPad", "name": "Pad_neck_gnd",
             "x": 3.0, "y": 4.5},
            {"type": "SolderPad", "name": "Pad_mid_hot",
             "x": 3.0, "y": 7.5},
            {"type": "SolderPad", "name": "Pad_mid_gnd",
             "x": 3.0, "y": 8.5},
            {"type": "SolderPad", "name": "Pad_bridge_hot",
             "x": 3.0, "y": 11.5},
            {"type": "SolderPad", "name": "Pad_bridge_gnd",
             "x": 3.0, "y": 12.5},

            {"_type": "LeverSwitch", "name": "SW",
             "x": 8.0, "y": 8.0, "type": "DP3T_5pos"},

            {"type": "PotentiometerPanel", "name": "VOL",
             "x": 14.0, "y": 4.0, "resistance": "250K",
             "taper": "LOG"},
            {"type": "PotentiometerPanel", "name": "TONE_neck",
             "x": 14.0, "y": 8.0, "resistance": "250K",
             "taper": "LIN"},
            {"type": "PotentiometerPanel", "name": "TONE_bridge",
             "x": 14.0, "y": 12.0, "resistance": "250K",
             "taper": "LIN"},

            {"type": "RadialCeramicDiskCapacitor", "name": "C_tone",
             "x1": 16.0, "y1": 8.5, "x2": 17.0, "y2": 8.5,
             "value": "22nF"},
            {"_type": "OpenJack1_4", "name": "J_out",
             "x": 25.0, "y": 8.0, "type": "MONO"},
            {"_type": "GroundSymbol", "name": "GND",
             "x": 20.0, "y": 18.0, "type": "DEFAULT"},
        ],
    })
    assert res["errors"] == [], f"batch errors: {res['errors']}"
    assert res["added"] == 16

    # Lock in pin counts on the guitar-specific multi-pin components.
    expected_pins = {
        "PU_neck":     1,   # SingleCoilPickup is single-anchor by design
        "SW":         10,   # DP3T_5pos lever switch
        "VOL":         3,   # 3-lug pot
        "J_out":       3,   # OpenJack1_4 (refactored last round)
    }
    for name, want in expected_pins.items():
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": pid, "name": name})
        assert len(pins) == want, (
            f"{name}: expected {want} pins, got {len(pins)}"
        )

    wires = [
        ("PU_neck",   "Pad_neck_hot"),
        ("PU_neck",   "Pad_neck_gnd"),
        ("PU_mid",    "Pad_mid_hot"),
        ("PU_mid",    "Pad_mid_gnd"),
        ("PU_bridge", "Pad_bridge_hot"),
        ("PU_bridge", "Pad_bridge_gnd"),
        ("Pad_neck_hot",   "SW"),
        ("Pad_mid_hot",    "SW"),
        ("Pad_bridge_hot", "SW"),
        ("SW", "VOL"),
        ("VOL", "J_out"),
        ("VOL", "TONE_neck"),
        ("TONE_neck", "C_tone"),
        ("C_tone", "GND"),
        ("Pad_neck_gnd",   "GND"),
        ("Pad_mid_gnd",    "GND"),
        ("Pad_bridge_gnd", "GND"),
        ("J_out",          "GND"),
    ]
    sw_lugs: set[int] = set()
    for src, dst in wires:
        r = _call(mcp_fixture, "connect", {
            "project_id": pid, "from_name": src, "to_name": dst,
        })
        if r["from"]["name"] == "SW":
            sw_lugs.add(r["from"]["pin"])
        if r["to"]["name"] == "SW":
            sw_lugs.add(r["to"]["pin"])

    # The selector should land on >1 distinct lug — otherwise nearest-pin
    # heuristic is collapsing across 10 control points.
    assert len(sw_lugs) >= 2, f"SW lugs collapsed: {sw_lugs}"

    rep = _call(mcp_fixture, "validate", {"project_id": pid})
    assert rep["ok"], f"validate errors: {rep['errors']}"

    out = tmp_path / "strat.diy"
    _call(mcp_fixture, "save", {"project_id": pid, "path": str(out)})
    rr = _call(mcp_fixture, "read_diy", {
        "project_id": f"{pid}_rt", "path": str(out),
    })
    assert rr["warnings"] == []
    assert rr["components"] == 16 + len(wires)

    # render_svg(return_content) must populate both 'content' and 'svg'
    # so callers expecting either key get the payload (the dual-key fix
    # this stress test surfaced).
    svg_res = _call(mcp_fixture, "render_svg",
                    {"project_id": pid, "return_content": True})
    assert "<svg" in svg_res["content"]
    assert "<svg" in svg_res["svg"]
    assert svg_res["content"] == svg_res["svg"]


def test_end_to_end_tube_amp_psu(mcp_fixture, tmp_path):
    """Seventh real-world stress test: tube-amp power supply.
    Sibling to the LPB-1, Champ, Big Muff, feedback-amp,
    two-channel-amp, and Strat tests.

    Probes the power-supply domain (AC inlet -> rectifier ->
    multi-stage filter chain -> DC out), exercising components no
    prior test wired end-to-end:
    - ElectrolyticCanCapacitor (3 pins, multi-section)
    - PlasticDCJack (3 pins, refactored last round)
    - BridgeRectifier (4 pins: +, ~, ~, -)
    - IECSocket (3 pins: L/N/E)
    - FuseHolderPanel (2 pins)
    - AudioTransformer used as a power transformer

    Specifically catches:
    - 'value' (singular) on ElectrolyticCanCapacitor must surface a
      'Did you mean values?' hint — the field is plural because the
      cap holds multiple sections.
    """
    pid = "psu"
    _call(mcp_fixture, "create_project", {
        "project_id": pid, "title": "Tube amp PSU",
        "width_cm": 30, "height_cm": 18,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": pid,
        "components": [
            {"_type": "IECSocket", "name": "AC_in",
             "x": 1.0, "y": 2.0},
            {"_type": "FuseHolderPanel", "name": "F1",
             "x": 3.5, "y": 2.0, "value": "1A SB"},
            {"type": "AudioTransformer", "name": "PT",
             "x": 6.0, "y": 2.0, "value": "Hammond 269BX"},
            {"type": "BridgeRectifier", "name": "BR1",
             "x": 11.0, "y": 4.0, "value": "GBPC2502"},
            {"_type": "ElectrolyticCanCapacitor", "name": "C_can",
             "x": 13.0, "y": 6.0,
             "values": ["40uF", "40uF", "40uF", "40uF"]},
            {"type": "RadialElectrolytic", "name": "C2",
             "x1": 18.0, "y1": 6.0, "x2": 18.0, "y2": 8.0,
             "value": "22uF"},
            {"type": "RadialElectrolytic", "name": "C3",
             "x1": 22.0, "y1": 6.0, "x2": 22.0, "y2": 8.0,
             "value": "22uF"},
            {"type": "Resistor", "name": "R_drop1",
             "x1": 16.0, "y1": 6.0, "x2": 17.0, "y2": 6.0,
             "value": "10K"},
            {"type": "Resistor", "name": "R_drop2",
             "x1": 20.0, "y1": 6.0, "x2": 21.0, "y2": 6.0,
             "value": "10K"},
            {"type": "Resistor", "name": "R_bleed",
             "x1": 13.0, "y1": 8.0, "x2": 13.0, "y2": 10.0,
             "value": "220K"},
            {"_type": "PlasticDCJack", "name": "DC_out",
             "x": 26.0, "y": 6.0, "value": "B+ tap"},
            {"_type": "GroundSymbol", "name": "GND",
             "x": 13.0, "y": 12.0, "type": "DEFAULT"},
        ],
    })
    assert res["errors"] == [], f"batch errors: {res['errors']}"
    assert res["added"] == 12

    # Lock in pin counts for the PSU-specific components.
    expected_pins = {
        "AC_in":   3,  # IECSocket: L / N / Earth
        "F1":      2,  # FuseHolderPanel
        "PT":      6,  # AudioTransformer
        "BR1":     4,  # +, ~, ~, -
        "C_can":   3,  # multi-section can cap
        "DC_out":  3,  # PlasticDCJack
    }
    for name, want in expected_pins.items():
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": pid, "name": name})
        assert len(pins) == want, (
            f"{name}: expected {want} pins, got {len(pins)}"
        )

    wires = [
        ("AC_in", "F1"), ("F1", "PT"), ("PT", "BR1"), ("PT", "GND"),
        ("BR1", "C_can"), ("BR1", "GND"),
        ("C_can", "R_drop1"), ("R_drop1", "C2"),
        ("C2", "R_drop2"), ("R_drop2", "C3"),
        ("C3", "DC_out"),
        ("C_can", "R_bleed"), ("R_bleed", "GND"),
        ("C2", "GND"), ("C3", "GND"), ("DC_out", "GND"),
    ]
    can_pins: set[int] = set()
    for src, dst in wires:
        r = _call(mcp_fixture, "connect", {
            "project_id": pid, "from_name": src, "to_name": dst,
        })
        if r["from"]["name"] == "C_can":
            can_pins.add(r["from"]["pin"])
        if r["to"]["name"] == "C_can":
            can_pins.add(r["to"]["pin"])

    # The can cap is multi-section; with this many wires touching it,
    # at least 2 of its 3 pins should see action.
    assert len(can_pins) >= 2, f"C_can wires collapsed: {can_pins}"

    rep = _call(mcp_fixture, "validate", {"project_id": pid})
    assert rep["ok"], f"validate errors: {rep['errors']}"

    out = tmp_path / "psu.diy"
    _call(mcp_fixture, "save", {"project_id": pid, "path": str(out)})
    rr = _call(mcp_fixture, "read_diy", {
        "project_id": f"{pid}_rt", "path": str(out),
    })
    assert rr["warnings"] == []
    assert rr["components"] == 12 + len(wires)


def test_end_to_end_stompbox_enclosure(mcp_fixture, tmp_path):
    """Eighth real-world stress test: top-down stompbox enclosure
    (chassis panel + cutouts + footswitch + LED indicator + jacks +
    pots + labels). Sibling to the prior 7 stress tests.

    Probes the chassis/enclosure domain:
    - ChassisPanel + EllipticalCutout + RectangularCutout — no prior
      end-to-end test exercised cutouts through save/load.
    - 3PDT MiniToggleSwitch wired as a true-bypass network — the
      footswitch's 9 lugs must lay out as a 3×3 grid (3 throws × 3
      poles), not a single column, so wires from different angles
      can actually land on different lugs.
    - Mixed top-panel hardware density (jacks, pots, LED, DC inlet).
    """
    pid = "box"
    _call(mcp_fixture, "create_project", {
        "project_id": pid, "title": "Stompbox enclosure",
        "width_cm": 12, "height_cm": 12,
    })
    res = _call(mcp_fixture, "add_components", {
        "project_id": pid,
        "components": [
            {"type": "ChassisPanel", "name": "Box",
             "x1": 0.5, "y1": 0.5, "x2": 5.0, "y2": 4.1,
             "value": "1590B"},
            {"type": "EllipticalCutout", "name": "Hole_FSW",
             "x1": 2.5, "y1": 3.3, "x2": 3.0, "y2": 3.8,
             "value": "3PDT"},
            {"type": "EllipticalCutout", "name": "Hole_in",
             "x1": 0.4, "y1": 1.5, "x2": 0.7, "y2": 1.8,
             "value": "input"},
            {"type": "EllipticalCutout", "name": "Hole_out",
             "x1": 4.8, "y1": 1.5, "x2": 5.1, "y2": 1.8,
             "value": "output"},
            {"type": "EllipticalCutout", "name": "Hole_dc",
             "x1": 2.6, "y1": 0.2, "x2": 2.9, "y2": 0.5,
             "value": "9V"},
            {"type": "RectangularCutout", "name": "Hole_LED",
             "x1": 2.6, "y1": 2.4, "x2": 2.9, "y2": 2.7,
             "value": "LED bezel"},
            {"_type": "MiniToggleSwitch", "name": "FSW",
             "x": 2.7, "y": 3.5, "switch_type": "_3PDT"},
            {"_type": "OpenJack1_4", "name": "J_in",
             "x": 0.5, "y": 1.6, "type": "MONO"},
            {"_type": "OpenJack1_4", "name": "J_out",
             "x": 4.9, "y": 1.6, "type": "MONO"},
            {"_type": "PlasticDCJack", "name": "DC",
             "x": 2.7, "y": 0.3},
            {"type": "LED", "name": "LED1",
             "x1": 2.7, "y1": 2.4, "x2": 2.7, "y2": 2.7,
             "value": "red"},
            {"type": "Resistor", "name": "R_LED",
             "x1": 2.5, "y1": 2.4, "x2": 2.5, "y2": 2.1,
             "value": "4K7"},
            {"type": "PotentiometerPanel", "name": "VOL",
             "x": 1.2, "y": 1.0, "resistance": "100K"},
            {"type": "PotentiometerPanel", "name": "TONE",
             "x": 2.7, "y": 1.0, "resistance": "20K"},
            {"type": "PotentiometerPanel", "name": "GAIN",
             "x": 4.2, "y": 1.0, "resistance": "100K"},
            {"type": "Label", "name": "L_vol",
             "x": 1.2, "y": 0.7, "text": "VOLUME"},
            {"type": "Label", "name": "L_tone",
             "x": 2.7, "y": 0.7, "text": "TONE"},
            {"type": "Label", "name": "L_gain",
             "x": 4.2, "y": 0.7, "text": "GAIN"},
            {"_type": "GroundSymbol", "name": "GND",
             "x": 2.7, "y": 4.0, "type": "DEFAULT"},
        ],
    })
    assert res["errors"] == [], f"batch errors: {res['errors']}"
    assert res["added"] == 19

    # Lock in pin counts on the multi-pin hardware.
    for name, want in [("FSW", 9), ("J_in", 3), ("DC", 3), ("LED1", 2)]:
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": pid, "name": name})
        assert len(pins) == want, f"{name}: want {want}, got {len(pins)}"

    wires = [
        ("J_in", "FSW"), ("FSW", "J_out"),
        ("FSW", "LED1"), ("LED1", "R_LED"), ("R_LED", "GND"),
        ("DC", "FSW"),
        ("J_in", "GND"), ("J_out", "GND"), ("DC", "GND"),
        ("VOL", "GND"), ("TONE", "GND"), ("GAIN", "GND"),
    ]
    fsw_lugs: set[int] = set()
    for src, dst in wires:
        r = _call(mcp_fixture, "connect", {
            "project_id": pid, "from_name": src, "to_name": dst,
        })
        if r["from"]["name"] == "FSW":
            fsw_lugs.add(r["from"]["pin"])
        if r["to"]["name"] == "FSW":
            fsw_lugs.add(r["to"]["pin"])

    # 3PDT must lay out as a 3×3 grid, not a single column. Wires
    # coming from physically different positions (J_in west, J_out
    # east, DC north, LED north) MUST land on at least 2 distinct
    # lugs — a single-column layout would force all of them to lug 0.
    assert len(fsw_lugs) >= 2, (
        f"3PDT lugs collapsed to a single column: {fsw_lugs}"
    )

    rep = _call(mcp_fixture, "validate", {"project_id": pid})
    assert rep["ok"], f"validate errors: {rep['errors']}"

    out = tmp_path / "box.diy"
    _call(mcp_fixture, "save", {"project_id": pid, "path": str(out)})
    rr = _call(mcp_fixture, "read_diy", {
        "project_id": f"{pid}_rt", "path": str(out),
    })
    assert rr["warnings"] == []
    assert rr["components"] == 19 + len(wires)

    # Cutouts must render alongside hardware.
    svg = _call(mcp_fixture, "render_svg",
                {"project_id": pid, "return_content": True})
    assert "<svg" in svg["svg"]


def test_3pdt_lug_layout_is_a_grid_not_a_column(mcp_fixture):
    """A 3PDT footswitch lays out 9 lugs as a 3×3 grid (3 throws × 3
    poles), so wires coming from different physical positions land
    on different lugs. Regression: a single-column layout would
    force everything to lug 0 via the nearest-pin heuristic.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "p", "width_cm": 10, "height_cm": 10})
    _call(mcp_fixture, "add_component", {
        "project_id": "p",
        "component": {"_type": "MiniToggleSwitch", "name": "SW",
                      "x": 5.0, "y": 5.0, "switch_type": "_3PDT"},
    })
    pins = _call(mcp_fixture, "get_pins", {"project_id": "p", "name": "SW"})
    # 3 distinct x AND 3 distinct y across the 9 pins.
    xs = {round(p["x"], 3) for p in pins}
    ys = {round(p["y"], 3) for p in pins}
    assert len(xs) == 3, f"3PDT x-spread is {xs}, expected 3 distinct cols"
    assert len(ys) == 3, f"3PDT y-spread is {ys}, expected 3 distinct rows"


def test_misspelled_field_suggests_correct_name(mcp_fixture):
    """If an LLM passes 'value' to a component whose field is 'values',
    the error must say 'Did you mean values?' — not just the raw
    'unexpected keyword argument' message.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "p", "width_cm": 10, "height_cm": 8})
    res = _call(mcp_fixture, "add_components", {
        "project_id": "p",
        "components": [{"_type": "ElectrolyticCanCapacitor", "name": "C",
                        "x": 1.0, "y": 1.0, "value": "20uF"}],
    })
    assert res["added"] == 0
    err = res["errors"][0]["error"]
    assert "Did you mean" in err
    assert "values" in err


def test_save_returns_xml_under_both_keys(mcp_fixture):
    """save(return_content=True) populates both 'content' (generic) and
    'xml' (descriptive). Regression for an LLM guessing the descriptive
    name based on the tool's purpose.
    """
    _call(mcp_fixture, "create_project",
          {"project_id": "p", "width_cm": 10, "height_cm": 8})
    _call(mcp_fixture, "add_component", {
        "project_id": "p",
        "component": {"type": "SolderPad", "name": "P", "x": 1.0, "y": 1.0},
    })
    res = _call(mcp_fixture, "save",
                {"project_id": "p", "return_content": True})
    assert "<project" in res["content"]
    assert "<project" in res["xml"]
    assert res["content"] == res["xml"]


def test_single_anchor_components_expose_all_pins(mcp_fixture):
    """Pin every affected class so any future inline-pts regression
    surfaces immediately. Each entry is (component_dict, expected_count).
    """
    cases = [
        # 5 pins
        ({"_type": "CliffJack1_4", "name": "J1",
          "x": 1.0, "y": 1.0, "type": "MONO"}, 5),
        # 3 pins (STEREO has the switched ring)
        ({"_type": "ClosedJack1_4", "name": "J2",
          "x": 1.0, "y": 2.0, "type": "STEREO"}, 3),
        # 2 pins (MONO)
        ({"_type": "ClosedJack1_4", "name": "J3",
          "x": 1.0, "y": 3.0, "type": "MONO"}, 2),
        # OpenJack1_4 — 3 pins (tip / sleeve / switched ring).
        ({"_type": "OpenJack1_4", "name": "J4",
          "x": 1.0, "y": 4.0, "type": "STEREO"}, 3),
        # NeutrikJack1_4 — 4 contacts (tip / ring / sleeve / mounting).
        ({"_type": "NeutrikJack1_4", "name": "J5",
          "x": 1.0, "y": 5.0}, 4),
        # PlasticDCJack — 3-contact barrel jack
        ({"_type": "PlasticDCJack", "name": "J6",
          "x": 1.0, "y": 6.0}, 3),
        # RCAJack — 2 pins.
        ({"_type": "RCAJack", "name": "J7",
          "x": 1.0, "y": 7.0}, 2),
        # 3-pin transistor packages
        ({"_type": "TransistorTO220", "name": "Q1",
          "x": 1.0, "y": 8.0}, 3),
        ({"_type": "TransistorTO126", "name": "Q2",
          "x": 1.0, "y": 9.0}, 3),
        ({"_type": "TransistorTO1", "name": "Q3",
          "x": 1.0, "y": 10.0}, 3),
        ({"_type": "SMDResistor", "name": "RS",
          "x": 1.0, "y": 11.0}, 2),
        ({"_type": "SMDCapacitor", "name": "CS",
          "x": 1.0, "y": 12.0}, 2),
    ]
    _call(mcp_fixture, "create_project",
          {"project_id": "p", "width_cm": 20, "height_cm": 20})
    for cdict, _ in cases:
        _call(mcp_fixture, "add_component",
              {"project_id": "p", "component": cdict})
    for cdict, want in cases:
        pins = _call(mcp_fixture, "get_pins",
                     {"project_id": "p", "name": cdict["name"]})
        assert len(pins) == want, (
            f"{cdict['_type']}: expected {want} pins, got {len(pins)}"
        )


def test_stats(mcp_fixture):
    """stats summarizes counts + bbox."""
    _call(mcp_fixture, "create_project", {"project_id": "st",
                                          "width_cm": 10, "height_cm": 8})
    _call(mcp_fixture, "add_component", {"project_id": "st",
        "component": {"type": "SolderPad", "name": "P1", "x": 1.0, "y": 1.0}})
    _call(mcp_fixture, "add_component", {"project_id": "st",
        "component": {"type": "Resistor", "name": "R1",
                      "x1": 2.0, "y1": 1.5, "x2": 2.0, "y2": 2.5}})
    res = _call(mcp_fixture, "stats", {"project_id": "st"})
    assert res["components"] == 2
    by = {e["type"]: e["count"] for e in res["by_type"]}
    assert by["SolderPad"] == 1
    assert by["Resistor"] == 1
    bb = res["bbox_in"]
    assert bb["min_x"] == 1.0
    assert bb["max_x"] == 2.0
    assert bb["min_y"] == 1.0
    assert bb["max_y"] == 2.5
    assert bb["width"] == pytest.approx(1.0)
    assert bb["height"] == pytest.approx(1.5)
