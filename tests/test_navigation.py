"""Tests for navigation tool state."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ada_mcp.tools.navigation import (
    _ensure_file_open,
    clear_open_files_cache,
)


@pytest.mark.asyncio
async def test_restarted_client_reopens_source(tmp_path):
    """A new ALS client receives didOpen even for an already used source."""
    source = tmp_path / "sample.ads"
    source.write_text("package Sample is end Sample;\n")
    first_client = AsyncMock()
    second_client = AsyncMock()
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
    client = AsyncMock()
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
    client = AsyncMock()
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
