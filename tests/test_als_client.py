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


@pytest.mark.asyncio
async def test_indexing_waits_for_progress_end():
    """Workspace readiness follows ALS work-done progress."""
    process = MagicMock()
    process.returncode = None
    client = ALSClient(process)

    await client._handle_progress(
        {
            "token": "index-1",
            "value": {"kind": "begin", "title": "Indexing"},
        }
    )
    waiter = asyncio.create_task(client.wait_for_indexing(timeout=0.5))
    await asyncio.sleep(0)
    assert not waiter.done()

    await client._handle_progress(
        {
            "token": "index-1",
            "value": {"kind": "end"},
        }
    )
    assert await waiter is True


@pytest.mark.asyncio
async def test_indexing_without_progress_is_not_complete():
    """An absent indexing signal cannot be reported as a complete index."""
    process = MagicMock()
    process.returncode = None
    client = ALSClient(process)

    assert await client.wait_for_indexing(timeout=0.01) is False


@pytest.mark.asyncio
async def test_diagnostic_publication_advances_generation():
    """Even an empty publication proves that ALS analyzed a document."""
    process = MagicMock()
    process.returncode = None
    client = ALSClient(process)
    uri = "file:///tmp/sample.ads"
    waiter = asyncio.create_task(
        client.wait_for_diagnostics(uri, after_generation=0, timeout=0.5)
    )
    await asyncio.sleep(0)

    await client._handle_diagnostics(
        {
            "uri": uri,
            "diagnostics": [],
        }
    )

    assert await waiter is True
    assert await client.diagnostics_generation(uri) == 1


@pytest.mark.asyncio
async def test_diagnostic_wait_uses_last_publication():
    """A duplicate intermediate publication does not expose stale state."""
    process = MagicMock()
    process.returncode = None
    client = ALSClient(process)
    uri = "file:///tmp/sample.ads"
    waiter = asyncio.create_task(
        client.wait_for_diagnostics(uri, after_generation=0, timeout=0.5)
    )

    await client._handle_diagnostics(
        {
            "uri": uri,
            "diagnostics": [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                    "message": "stale",
                }
            ],
        }
    )
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await client._handle_diagnostics(
        {
            "uri": uri,
            "diagnostics": [],
        }
    )

    assert await waiter is True
    assert await client.diagnostics_generation(uri) == 2
    assert await client.get_diagnostics(uri) == {uri: []}
