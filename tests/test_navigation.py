"""Tests for navigation tool state."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ada_mcp.als.client import ALSClient
from ada_mcp.tools.navigation import (
    _ensure_file_open,
    clear_open_files_cache,
    handle_type_definition,
)


def _mock_client() -> AsyncMock:
    """Create an ALS client mock whose startup source set is unchanged."""
    client = AsyncMock(spec=ALSClient)
    client.is_new_project_source.return_value = False
    return client


@pytest.mark.asyncio
async def test_restarted_client_reopens_source(tmp_path):
    """A new ALS client receives didOpen even for an already used source."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    first_client = _mock_client()
    second_client = _mock_client()
    clear_open_files_cache()

    await _ensure_file_open(first_client, str(source))
    await _ensure_file_open(first_client, str(source))
    await _ensure_file_open(second_client, str(source))

    assert first_client.send_notification.await_count == 1
    assert second_client.send_notification.await_count == 1


@pytest.mark.asyncio
async def test_edited_source_is_synchronized_with_did_change(tmp_path):
    """A source edit replaces the text held by the existing ALS client."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    client = _mock_client()
    clear_open_files_cache()

    assert await _ensure_file_open(client, str(source)) is True
    source.write_text(
        "package Sample is\n"
        "   Changed : constant := 1;\n"
        "end Sample;\n"
    )
    assert await _ensure_file_open(client, str(source)) is True
    assert await _ensure_file_open(client, str(source)) is False

    assert client.send_notification.await_count == 2
    method, params = client.send_notification.await_args_list[1].args
    assert method == "textDocument/didChange"
    assert params["textDocument"]["version"] == 2
    assert params["contentChanges"] == [{"text": source.read_text()}]


@pytest.mark.asyncio
async def test_parallel_source_sync_sends_one_did_open(tmp_path):
    """Parallel semantic requests must share one LSP document lifecycle."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    client = _mock_client()
    clear_open_files_cache()

    async def delayed_notification(*_args, **_kwargs):
        # Make both callers observe the unopened file before either
        # notification completes.
        await asyncio.sleep(0)

    client.send_notification.side_effect = delayed_notification

    results = await asyncio.gather(
        _ensure_file_open(client, str(source)),
        _ensure_file_open(client, str(source)),
    )

    assert results == [True, False]
    client.send_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_project_source_is_announced_before_did_open(tmp_path):
    """A source created after ALS startup triggers one full project refresh."""
    source = tmp_path / "created.ads"
    source.write_text("package Created is end Created;\n")
    client = _mock_client()
    client.is_new_project_source = MagicMock(return_value=True)
    client.remember_project_source = MagicMock()
    client.indexing_generation.return_value = 7
    client.wait_for_indexing.return_value = True
    clear_open_files_cache()

    assert await _ensure_file_open(client, str(source)) is True
    assert await _ensure_file_open(client, str(source)) is False

    assert client.send_notification.await_args_list[0].args == (
        "workspace/didCreateFiles",
        {
            "files": [
                {
                    "uri": source.resolve().as_uri(),
                }
            ]
        },
    )
    assert client.send_notification.await_args_list[1].args == (
        "workspace/didChangeWatchedFiles",
        {
            "changes": [
                {
                    "uri": source.resolve().as_uri(),
                    "type": 1,
                }
            ]
        },
    )
    assert client.send_notification.await_args_list[2].args[0] == "textDocument/didOpen"
    client.send_request.assert_awaited_once_with(
        "workspace/executeCommand",
        {
            "command": "als-reload-project",
            "arguments": [],
        },
    )
    client.remember_project_source.assert_called_once_with(source)
    client.wait_for_indexing.assert_awaited_once_with(after_generation=7)


@pytest.mark.asyncio
async def test_deleted_open_source_is_closed_and_announced(tmp_path):
    """Deleting an open source closes it before refreshing the project."""
    source = tmp_path / "deleted.ads"
    source.write_text("package Deleted is end Deleted;\n")
    client = _mock_client()
    client.is_known_project_source = MagicMock(return_value=True)
    client.forget_project_source = MagicMock()
    client.indexing_generation.return_value = 11
    client.wait_for_indexing.return_value = True
    clear_open_files_cache()

    assert await _ensure_file_open(client, str(source)) is True
    source.unlink()
    assert await _ensure_file_open(client, str(source)) is None

    assert client.send_notification.await_args_list[1].args == (
        "textDocument/didClose",
        {
            "textDocument": {
                "uri": source.resolve().as_uri(),
            }
        },
    )
    assert client.send_notification.await_args_list[2].args == (
        "workspace/didDeleteFiles",
        {
            "files": [
                {
                    "uri": source.resolve().as_uri(),
                }
            ]
        },
    )
    assert client.send_notification.await_args_list[3].args == (
        "workspace/didChangeWatchedFiles",
        {
            "changes": [
                {
                    "uri": source.resolve().as_uri(),
                    "type": 3,
                }
            ]
        },
    )
    client.send_request.assert_awaited_once_with(
        "workspace/executeCommand",
        {
            "command": "als-reload-project",
            "arguments": [],
        },
    )
    client.forget_project_source.assert_called_once_with(source)
    client.wait_for_indexing.assert_awaited_once_with(after_generation=11)


@pytest.mark.asyncio
async def test_type_definition_explains_explicit_type_name_semantics(tmp_path):
    """An empty type-definition result directs explicit types to definition."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    client = _mock_client()
    client.send_request.return_value = []
    clear_open_files_cache()

    result = await handle_type_definition(
        client,
        file=str(source),
        line=1,
        column=9,
    )

    assert result["found"] is False
    assert "object or parameter identifier" in result["hint"]
    assert "ada_goto_definition" in result["hint"]
