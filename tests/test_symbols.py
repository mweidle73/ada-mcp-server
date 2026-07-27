"""Tests for workspace symbol indexing state."""

from unittest.mock import AsyncMock

import pytest

from ada_mcp.als.types import SymbolKind
from ada_mcp.tools.symbols import handle_workspace_symbols


@pytest.mark.asyncio
async def test_workspace_symbols_wait_for_complete_index():
    """A partial ALS index cannot masquerade as an empty search result."""
    client = AsyncMock()
    client.wait_for_indexing.return_value = False

    result = await handle_workspace_symbols(client, "Missing")

    assert result["complete"] is False
    assert result["count"] == 0
    assert "indexing did not complete" in result["error"]
    client.send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_workspace_result_is_complete_after_indexing():
    """An empty result is meaningful after ALS finishes indexing."""
    client = AsyncMock()
    client.wait_for_indexing.return_value = True
    client.send_request.return_value = []

    result = await handle_workspace_symbols(client, "Missing")

    assert result == {
        "symbols": [],
        "count": 0,
        "truncated": False,
        "complete": True,
    }


@pytest.mark.asyncio
async def test_workspace_symbol_truncation_uses_filtered_matches():
    """Unrelated symbol kinds must not make a filtered result look truncated."""
    client = AsyncMock()
    client.wait_for_indexing.return_value = True
    client.send_request.return_value = [
        {"name": "First", "kind": SymbolKind.FUNCTION},
        {"name": "Only_Package", "kind": SymbolKind.PACKAGE},
        {"name": "Second", "kind": SymbolKind.FUNCTION},
    ]

    result = await handle_workspace_symbols(
        client,
        "Symbol",
        kind="package",
        limit=2,
    )

    assert result["count"] == 1
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_workspace_symbol_truncation_detects_extra_filtered_match():
    """One matching result beyond the output limit marks it as truncated."""
    client = AsyncMock()
    client.wait_for_indexing.return_value = True
    client.send_request.return_value = [
        {"name": "First", "kind": SymbolKind.PACKAGE},
        {"name": "Ignored", "kind": SymbolKind.FUNCTION},
        {"name": "Second", "kind": SymbolKind.PACKAGE},
        {"name": "Third", "kind": SymbolKind.PACKAGE},
    ]

    result = await handle_workspace_symbols(
        client,
        "Package",
        kind="package",
        limit=2,
    )

    assert result["count"] == 2
    assert result["truncated"] is True
