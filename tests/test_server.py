"""Tests for the MCP server module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_tools():
    """Test that list_tools returns expected tools."""
    from ada_mcp.server import list_tools

    tools = await list_tools()

    assert len(tools) >= 3
    tool_names = [t.name for t in tools]
    assert "ada_goto_definition" in tool_names
    assert "ada_hover" in tool_names
    assert "ada_diagnostics" in tool_names

    workspace_symbols = next(
        tool for tool in tools if tool.name == "ada_workspace_symbols"
    )
    assert workspace_symbols.inputSchema["required"] == ["file", "query"]

    project_info = next(tool for tool in tools if tool.name == "ada_project_info")
    assert project_info.inputSchema["required"] == ["gpr_file"]
    assert "reuse the validated selection" in project_info.description


@pytest.mark.asyncio
async def test_call_tool_unknown():
    """Test that calling unknown tool returns error."""
    from ada_mcp.server import call_tool

    result = await call_tool("unknown_tool", {})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_call_tool_goto_definition():
    """Test ada_goto_definition tool call."""
    from ada_mcp.server import call_tool

    result = await call_tool(
        "ada_goto_definition",
        {
            "file": "/some/path/test.adb",
            "line": 10,
            "column": 5,
        },
    )

    assert len(result) == 1
    data = json.loads(result[0].text)
    # Currently returns "not implemented" - update when ALS is integrated
    assert "found" in data or "error" in data


@pytest.mark.asyncio
async def test_project_load_failure_discards_cached_client():
    """A failed project view must not remain cached after the request."""
    from ada_mcp.server import call_tool

    client = MagicMock()
    incomplete = {
        "complete": False,
        "reason": "project-load-failed",
        "project_file": "/test/project/abuild.gpr",
    }

    with (
        patch(
            "ada_mcp.server.get_als_client",
            new_callable=AsyncMock,
            return_value=client,
        ) as get_client,
        patch(
            "ada_mcp.server.handle_project_info",
            new_callable=AsyncMock,
            return_value=incomplete,
        ),
        patch(
            "ada_mcp.server._als_pool.discard_client",
            new_callable=AsyncMock,
        ) as discard,
    ):
        result = await call_tool(
            "ada_project_info",
            {"gpr_file": "/test/project/abuild.gpr"},
        )

    get_client.assert_awaited_once_with(
        file_path="/test/project/abuild.gpr",
        gpr_file="/test/project/abuild.gpr",
    )
    discard.assert_awaited_once_with("/test/project/abuild.gpr", client)
    assert json.loads(result[0].text) == incomplete


@pytest.mark.asyncio
async def test_project_info_selects_validated_client():
    """A validated explicit project becomes the source-tool project view."""
    from ada_mcp.server import call_tool

    client = MagicMock()
    complete = {
        "complete": True,
        "project_file": "/test/project/spawn_manager.gpr",
    }
    with (
        patch(
            "ada_mcp.server.get_als_client",
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch(
            "ada_mcp.server.handle_project_info",
            new_callable=AsyncMock,
            return_value=complete,
        ),
        patch(
            "ada_mcp.server._als_pool.select_client",
            new_callable=AsyncMock,
        ) as select,
    ):
        result = await call_tool(
            "ada_project_info",
            {"gpr_file": "/test/project/spawn_manager.gpr"},
        )

    select.assert_awaited_once_with(client)
    assert json.loads(result[0].text) == complete


@pytest.mark.asyncio
async def test_project_info_error_discards_selected_client():
    """A rejected explicit project must not remain selected in the pool."""
    from ada_mcp.server import call_tool

    client = MagicMock()
    with (
        patch(
            "ada_mcp.server.get_als_client",
            new_callable=AsyncMock,
            return_value=client,
        ),
        patch(
            "ada_mcp.server.handle_project_info",
            new_callable=AsyncMock,
            side_effect=RuntimeError("different project"),
        ),
        patch(
            "ada_mcp.server._als_pool.discard_client",
            new_callable=AsyncMock,
        ) as discard,
    ):
        result = await call_tool(
            "ada_project_info",
            {"gpr_file": "/test/project/spawn_manager.gpr"},
        )

    discard.assert_awaited_once_with("/test/project/spawn_manager.gpr", client)
    assert json.loads(result[0].text)["error"] == "different project"
