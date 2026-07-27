"""Tests for navigation tool state."""

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
