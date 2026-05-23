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
        "list_components", "get_component", "find_components",
        # Edits
        "add_component", "remove_component",
        "move_component", "move_node", "move_node_to",
        "rotate_component", "duplicate_component", "set_value", "add_wire",
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
