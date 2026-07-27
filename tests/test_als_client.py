"""Tests for the Ada Language Server protocol client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ada_mcp.als.client import ALSClient, LSPError


@pytest.mark.asyncio
async def test_closed_stdout_fails_pending_requests():
    """Requests fail immediately when their ALS connection closes."""
    process = MagicMock()
    process.returncode = None
    process.stdout = MagicMock()
    process.stdout.readline = AsyncMock(return_value=b"")
    client = ALSClient(process)
    pending = asyncio.get_running_loop().create_future()
    client._pending_requests[1] = pending

    await client._read_loop()

    with pytest.raises(LSPError, match="ALS connection closed"):
        await pending
    assert client._pending_requests == {}


@pytest.mark.asyncio
async def test_write_failure_removes_pending_request():
    """A request which cannot be written leaves no stale pending future."""
    process = MagicMock()
    process.returncode = None
    client = ALSClient(process)
    client._write_message = AsyncMock(side_effect=LSPError(-1, "write failed"))

    with pytest.raises(LSPError, match="write failed"):
        await client.send_request("test/request")

    assert client._pending_requests == {}
