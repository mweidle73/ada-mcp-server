"""Tests for synchronized Ada Language Server diagnostics."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ada_mcp.tools.diagnostics import handle_diagnostics
from ada_mcp.tools.navigation import clear_open_files_cache
from ada_mcp.utils.uri import file_to_uri


def diagnostic_client() -> AsyncMock:
    """Create the protocol state used by the diagnostics handler."""
    client = AsyncMock()
    client.send_notification = AsyncMock()
    client.diagnostics_generation = AsyncMock(return_value=0)
    client.wait_for_diagnostics = AsyncMock(return_value=True)
    client._diagnostics = {}
    client._diagnostics_lock = asyncio.Lock()
    return client


@pytest.mark.asyncio
async def test_file_diagnostics_are_complete_after_publication(tmp_path):
    """An empty result is complete only after the synchronized-file signal."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    client = diagnostic_client()
    client._diagnostics[file_to_uri(source)] = []
    clear_open_files_cache()

    result = await handle_diagnostics(client, file=str(source))

    assert result == {
        "diagnostics": [],
        "errorCount": 0,
        "warningCount": 0,
        "hintCount": 0,
        "totalCount": 0,
        "complete": True,
        "scope": "file",
    }
    client.wait_for_diagnostics.assert_awaited_once_with(
        file_to_uri(source),
        after_generation=0,
    )


@pytest.mark.asyncio
async def test_file_diagnostics_fail_loud_without_publication(tmp_path):
    """A missing ALS publication is not reported as a clean source."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    client = diagnostic_client()
    client.wait_for_diagnostics.return_value = False
    clear_open_files_cache()

    result = await handle_diagnostics(client, file=str(source))

    assert result["complete"] is False
    assert result["scope"] == "file"
    assert result["totalCount"] == 0
    assert "did not publish diagnostics" in result["error"]


@pytest.mark.asyncio
async def test_global_diagnostics_are_explicitly_cache_scoped():
    """Cached publications do not claim project-wide completeness."""
    client = diagnostic_client()

    result = await handle_diagnostics(client)

    assert result["complete"] is False
    assert result["scope"] == "published-cache"
