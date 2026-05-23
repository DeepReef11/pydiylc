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
        # Project lifecycle
        "create_project", "create_project_from_dict", "list_projects",
        "delete_project", "set_project_metadata",
        # Inspection
        "list_components", "get_component", "find_components", "get_pins",
        # Edits
        "add_component", "add_components", "remove_component",
        "move_component", "move_node", "move_node_to",
        "rotate_component", "duplicate_component",
        "set_value", "set_field", "add_wire", "connect",
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
    """Two canned workflow prompts."""
    import asyncio

    server = mcp_server.build_server()
    prompts = asyncio.run(server.list_prompts())
    names = {p.name for p in prompts}
    assert "build_pedal_layout" in names
    assert "modify_existing_layout" in names


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
    _call(mcp_fixture, "create_project",
          {"project_id": "v2", "width_cm": 5.0, "height_cm": 5.0})
    _call(mcp_fixture, "add_component", {"project_id": "v2",
        "component": {"type": "SolderPad", "name": "P1", "x": 100.0, "y": 100.0}})
    rep = _call(mcp_fixture, "validate", {"project_id": "v2"})
    off = [i for i in rep["issues"] if i["kind"] == "off_canvas"]
    assert off
    assert off[0]["name"] == "P1"


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
