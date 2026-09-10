"""Tests for workspace symbol indexing state."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ada_mcp.als.types import SymbolKind
from ada_mcp.tools.navigation import _ensure_file_open, clear_open_files_cache
from ada_mcp.tools.symbols import handle_document_symbols, handle_workspace_symbols


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
async def test_deleted_open_source_is_not_merged_into_workspace_symbols(tmp_path):
    """A deleted source must not survive in the open-document symbol view."""
    source = tmp_path / "deleted.ads"
    source.write_text("package Deleted is end Deleted;\n")
    client = AsyncMock()
    client.is_new_project_source = MagicMock(return_value=False)
    client.is_known_project_source = MagicMock(return_value=True)
    client.forget_project_source = MagicMock()
    client.indexing_generation.return_value = 3
    client.wait_for_indexing.return_value = True
    client.send_request.side_effect = [
        None,
        [
            {
                "name": "Deleted",
                "kind": SymbolKind.PACKAGE,
                "location": {
                    "uri": source.resolve().as_uri(),
                    "range": {
                        "start": {"line": 0, "character": 8},
                    },
                },
            }
        ],
    ]
    clear_open_files_cache()

    await _ensure_file_open(client, str(source))
    source.unlink()
    result = await handle_workspace_symbols(client, "Deleted")

    assert result == {
        "symbols": [],
        "count": 0,
        "truncated": False,
        "complete": True,
    }
    assert [request.args[0] for request in client.send_request.await_args_list] == [
        "workspace/executeCommand",
        "workspace/symbol",
    ]


@pytest.mark.asyncio
async def test_deleted_document_symbol_request_fails_explicitly(tmp_path):
    """A deleted document cannot return symbols cached by ALS."""
    source = tmp_path / "deleted.ads"
    source.write_text("package Deleted is end Deleted;\n")
    client = AsyncMock()
    client.is_new_project_source = MagicMock(return_value=False)
    client.is_known_project_source = MagicMock(return_value=True)
    client.forget_project_source = MagicMock()
    client.indexing_generation.return_value = 4
    client.wait_for_indexing.return_value = True
    clear_open_files_cache()

    await _ensure_file_open(client, str(source))
    source.unlink()
    result = await handle_document_symbols(client, str(source))

    assert result["symbols"] == []
    assert result["complete"] is False
    assert "File not found" in result["error"]
    client.send_request.assert_awaited_once_with(
        "workspace/executeCommand",
        {
            "command": "als-reload-project",
            "arguments": [],
        },
    )


@pytest.mark.asyncio
async def test_workspace_symbols_filter_source_deleted_after_pruning(tmp_path):
    """The final merged result rejects a source deleted during the query."""
    source = tmp_path / "deleted.ads"
    client = AsyncMock()
    client.wait_for_indexing.return_value = True
    client.send_request.side_effect = [
        [],
        [
            {
                "name": "Deleted",
                "kind": SymbolKind.PACKAGE,
                "range": {"start": {"line": 0, "character": 0}},
                "selectionRange": {"start": {"line": 0, "character": 8}},
            }
        ],
    ]

    with (
        patch(
            "ada_mcp.tools.symbols._prune_deleted_open_files",
            new=AsyncMock(),
        ),
        patch(
            "ada_mcp.tools.symbols._open_file_paths",
            return_value=[str(source)],
        ),
    ):
        result = await handle_workspace_symbols(client, "Deleted")

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


@pytest.mark.asyncio
async def test_workspace_symbols_include_open_documents(tmp_path):
    """Opening both Ada units must not hide their workspace symbols."""
    crypto_spec = tmp_path / "crypto.ads"
    crypto_body = tmp_path / "crypto.adb"
    crypto_spec.write_text("package Crypto is end Crypto;\n")
    crypto_body.write_text("package body Crypto is end Crypto;\n")
    client = AsyncMock()
    client.wait_for_indexing.return_value = True
    client.send_request.side_effect = [
        [],
        [
            {
                "name": "Crypto",
                "kind": SymbolKind.PACKAGE,
                "range": {"start": {"line": 0, "character": 0}},
                "selectionRange": {"start": {"line": 0, "character": 8}},
                "children": [
                    {
                        "name": "Get_File_Hash",
                        "kind": SymbolKind.FUNCTION,
                        "range": {"start": {"line": 21, "character": 3}},
                        "selectionRange": {"start": {"line": 21, "character": 12}},
                    }
                ],
            }
        ],
        [
            {
                "name": "Get_File_Hash",
                "kind": SymbolKind.FUNCTION,
                "range": {"start": {"line": 32, "character": 3}},
                "selectionRange": {"start": {"line": 32, "character": 12}},
            }
        ],
    ]

    with patch(
        "ada_mcp.tools.symbols._open_file_paths",
        return_value=[str(crypto_spec), str(crypto_body)],
    ):
        result = await handle_workspace_symbols(
            client,
            "Get_File_Hash",
            kind="function",
        )

    assert result == {
        "symbols": [
            {
                "name": "Get_File_Hash",
                "kind": "function",
                "file": str(crypto_spec),
                "line": 22,
                "column": 13,
                "containerName": "",
            },
            {
                "name": "Get_File_Hash",
                "kind": "function",
                "file": str(crypto_body),
                "line": 33,
                "column": 13,
                "containerName": "",
            },
        ],
        "count": 2,
        "truncated": False,
        "complete": True,
    }
