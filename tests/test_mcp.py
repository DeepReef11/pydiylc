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
        "list_component_types",
        "create_project",
        "create_project_from_dict",
        "add_component",
        "list_components",
        "remove_component",
        "save",
        "render_svg",
        "to_json",
        "read_diy",
    }
    missing = expected - names
    assert not missing, f"missing MCP tools: {missing}"


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
