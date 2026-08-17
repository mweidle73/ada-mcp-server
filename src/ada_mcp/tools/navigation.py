"""Navigation tools: goto definition, find references, hover."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

from ada_mcp.als.client import ALSClient, LSPError
from ada_mcp.utils.uri import file_to_uri, uri_to_file

logger = logging.getLogger(__name__)


async def handle_goto_definition(
    client: ALSClient,
    file: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """
    Navigate to the definition of a symbol at a given location.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file
        line: 1-based line number
        column: 1-based column number

    Returns:
        Dict with definition location or not found status
    """
    file_uri = file_to_uri(file)

    # Ensure file is open in ALS
    await _ensure_file_open(client, file)

    try:
        result = await client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": file_uri},
                "position": {
                    "line": line - 1,  # Convert to 0-based
                    "character": column - 1,
                },
            },
        )
    except LSPError as e:
        logger.error(f"LSP error in goto_definition: {e}")
        return {
            "found": False,
            "error": e.message,
            "context": {"file": file, "line": line, "column": column},
        }

    if not result:
        return {"found": False}

    # Handle both single location and array of locations
    if isinstance(result, list):
        location = result[0] if result else None
    else:
        location = result

    if not location:
        return {"found": False}

    # Handle LocationLink vs Location
    if "targetUri" in location:
        # LocationLink format
        target_uri = location["targetUri"]
        target_range = location.get("targetSelectionRange", location.get("targetRange", {}))
    else:
        # Location format
        target_uri = location.get("uri", "")
        target_range = location.get("range", {})

    start = target_range.get("start", {})
    target_file = uri_to_file(target_uri)

    # Get preview line
    preview = await _get_line_preview(target_file, start.get("line", 0))

    return {
        "found": True,
        "file": target_file,
        "line": start.get("line", 0) + 1,  # Convert to 1-based
        "column": start.get("character", 0) + 1,
        "preview": preview,
    }


async def handle_find_references(
    client: ALSClient,
    file: str,
    line: int,
    column: int,
    include_declaration: bool = True,
) -> dict[str, Any]:
    """
    Find all references to a symbol across the project.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file
        line: 1-based line number
        column: 1-based column number
        include_declaration: Whether to include the declaration in results

    Returns:
        Dict with list of references and count
    """
    file_uri = file_to_uri(file)

    # Ensure file is open in ALS
    await _ensure_file_open(client, file)

    try:
        result = await client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": file_uri},
                "position": {
                    "line": line - 1,
                    "character": column - 1,
                },
                "context": {"includeDeclaration": include_declaration},
            },
        )
    except LSPError as e:
        logger.error(f"LSP error in find_references: {e}")
        return {
            "references": [],
            "count": 0,
            "error": e.message,
            "context": {"file": file, "line": line, "column": column},
        }

    if not result:
        return {"references": [], "count": 0}

    references = []
    for loc in result:
        loc_uri = loc.get("uri", "")
        loc_range = loc.get("range", {})
        start = loc_range.get("start", {})

        ref_file = uri_to_file(loc_uri)
        ref_line = start.get("line", 0) + 1

        preview = await _get_line_preview(ref_file, start.get("line", 0))

        references.append(
            {
                "file": ref_file,
                "line": ref_line,
                "column": start.get("character", 0) + 1,
                "preview": preview,
            }
        )

    return {
        "references": references,
        "count": len(references),
    }


async def handle_type_definition(
    client: ALSClient,
    file: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """
    Navigate to the type definition of a symbol at a given location.

    This is useful for finding where a type is defined, not just where
    a variable is declared. For example, given a variable of type Config,
    this returns the location where Config type is defined.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file
        line: 1-based line number
        column: 1-based column number

    Returns:
        Dict with type definition location or not found status
    """
    file_uri = file_to_uri(file)

    # Ensure file is open in ALS
    await _ensure_file_open(client, file)

    try:
        result = await client.send_request(
            "textDocument/typeDefinition",
            {
                "textDocument": {"uri": file_uri},
                "position": {
                    "line": line - 1,  # Convert to 0-based
                    "character": column - 1,
                },
            },
        )
    except LSPError as e:
        logger.error(f"LSP error in type_definition: {e}")
        return {
            "found": False,
            "error": e.message,
            "context": {"file": file, "line": line, "column": column},
        }

    if not result:
        return {
            "found": False,
            "hint": (
                "Place the cursor on an object or parameter identifier. "
                "Use ada_goto_definition when the cursor is already on an "
                "explicit type name."
            ),
        }

    # Handle both single location and array of locations
    if isinstance(result, list):
        location = result[0] if result else None
    else:
        location = result

    if not location:
        return {"found": False}

    # Handle LocationLink vs Location
    if "targetUri" in location:
        target_uri = location["targetUri"]
        target_range = location.get("targetSelectionRange", location.get("targetRange", {}))
    else:
        target_uri = location.get("uri", "")
        target_range = location.get("range", {})

    start = target_range.get("start", {})
    target_file = uri_to_file(target_uri)

    # Get preview line
    preview = await _get_line_preview(target_file, start.get("line", 0))

    return {
        "found": True,
        "file": target_file,
        "line": start.get("line", 0) + 1,  # Convert to 1-based
        "column": start.get("character", 0) + 1,
        "preview": preview,
    }


async def handle_implementation(
    client: ALSClient,
    file: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """
    Navigate from a declaration to its implementation/body.

    This is useful for jumping from a spec (.ads) to the body (.adb).
    For example, given a function declaration in a package spec,
    this returns the location of the function body.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file
        line: 1-based line number
        column: 1-based column number

    Returns:
        Dict with implementation location or not found status
    """
    file_uri = file_to_uri(file)

    # Ensure file is open in ALS
    await _ensure_file_open(client, file)

    try:
        result = await client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": file_uri},
                "position": {
                    "line": line - 1,  # Convert to 0-based
                    "character": column - 1,
                },
            },
        )
    except LSPError as e:
        logger.error(f"LSP error in implementation: {e}")
        return {
            "found": False,
            "error": e.message,
            "context": {"file": file, "line": line, "column": column},
        }

    if not result:
        return {"found": False}

    # Handle both single location and array of locations
    if isinstance(result, list):
        location = result[0] if result else None
    else:
        location = result

    if not location:
        return {"found": False}

    # Handle LocationLink vs Location
    if "targetUri" in location:
        target_uri = location["targetUri"]
        target_range = location.get("targetSelectionRange", location.get("targetRange", {}))
    else:
        target_uri = location.get("uri", "")
        target_range = location.get("range", {})

    start = target_range.get("start", {})
    target_file = uri_to_file(target_uri)

    # Get preview line
    preview = await _get_line_preview(target_file, start.get("line", 0))

    return {
        "found": True,
        "file": target_file,
        "line": start.get("line", 0) + 1,  # Convert to 1-based
        "column": start.get("character", 0) + 1,
        "preview": preview,
    }


async def handle_hover(
    client: ALSClient,
    file: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """
    Get type information and documentation for a symbol.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file
        line: 1-based line number
        column: 1-based column number

    Returns:
        Dict with hover information
    """
    file_uri = file_to_uri(file)

    # Ensure file is open in ALS
    await _ensure_file_open(client, file)

    try:
        result = await client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": file_uri},
                "position": {
                    "line": line - 1,
                    "character": column - 1,
                },
            },
        )
    except LSPError as e:
        logger.error(f"LSP error in hover: {e}")
        return {
            "found": False,
            "error": e.message,
            "context": {"file": file, "line": line, "column": column},
        }

    if not result:
        return {"found": False}

    contents = result.get("contents", {})

    # Parse contents - can be string, MarkupContent, or MarkedString[]
    if isinstance(contents, str):
        text = contents
    elif isinstance(contents, dict):
        text = contents.get("value", str(contents))
    elif isinstance(contents, list):
        # Array of MarkedString
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("value", str(item)))
        text = "\n".join(parts)
    else:
        text = str(contents)

    return {
        "found": True,
        "contents": text,
    }


@dataclass
class _OpenFile:
    """Text and LSP version last synchronized with one ALS client."""

    text: str
    version: int


# Track open files per ALS client. A restarted server receives a new client and
# must therefore see fresh didOpen notifications for every source it analyzes.
_open_files: WeakKeyDictionary[ALSClient, dict[str, _OpenFile]] = WeakKeyDictionary()
_open_file_locks: WeakKeyDictionary[ALSClient, asyncio.Lock] = WeakKeyDictionary()


def _open_file_paths(client: ALSClient) -> list[str]:
    """Return the source paths synchronized with one ALS client."""
    return sorted(uri_to_file(uri) for uri in _open_files.get(client, {}))


async def _prune_deleted_open_files(client: ALSClient) -> None:
    """Close and announce open sources which disappeared from the filesystem."""
    for file_path in _open_file_paths(client):
        if not Path(file_path).exists():
            await _ensure_file_open(client, file_path)


async def _ensure_file_open(
    client: ALSClient,
    file_path: str,
    force_change: bool = False,
) -> bool | None:
    """
    Synchronize a file with ALS.

    Returns True when didOpen or didChange was sent, False when the server
    already has the current text and None when the path does not exist.
    """
    # MCP dispatches tool calls concurrently. Keep the LSP document lifecycle
    # atomic per ALS client without serializing the semantic requests which
    # follow this short synchronization step.
    client_lock = _open_file_locks.setdefault(client, asyncio.Lock())
    async with client_lock:
        return await _synchronize_file(client, file_path, force_change)


async def _synchronize_file(
    client: ALSClient,
    file_path: str,
    force_change: bool,
) -> bool | None:
    """Synchronize one file while holding its ALS client's document lock."""
    file_uri = file_to_uri(file_path)
    client_open_files = _open_files.setdefault(client, {})

    path = Path(file_path)
    if not path.exists():
        open_file = client_open_files.pop(file_uri, None)
        is_known_source = client.is_known_project_source(path)
        if open_file is not None:
            await client.send_notification(
                "textDocument/didClose",
                {
                    "textDocument": {
                        "uri": file_uri,
                    }
                },
            )

        if open_file is not None or is_known_source:
            indexing_generation = await client.indexing_generation()
            await client.send_notification(
                "workspace/didDeleteFiles",
                {
                    "files": [
                        {
                            "uri": file_uri,
                        }
                    ]
                },
            )
            await client.send_notification(
                "workspace/didChangeWatchedFiles",
                {
                    "changes": [
                        {
                            "uri": file_uri,
                            "type": 3,
                        }
                    ]
                },
            )
            # The file-operation notification schedules a project reload, but
            # its indexing progress is not a processing barrier for the
            # watched-file notification queued behind it. ALS's reload command
            # is a fence job and therefore makes both notifications visible
            # before the final index generation is accepted.
            await client.send_request(
                "workspace/executeCommand",
                {
                    "command": "als-reload-project",
                    "arguments": [],
                },
            )
            client.forget_project_source(path)
            if not await client.wait_for_indexing(
                after_generation=indexing_generation,
            ):
                raise LSPError(
                    -1,
                    f"Ada Language Server did not finish removing project source: {file_path}",
                )

        logger.warning(f"File not found: {file_path}")
        return None

    text = path.read_text()
    open_file = client_open_files.get(file_uri)
    if open_file is not None:
        if open_file.text == text and not force_change:
            return False

        version = open_file.version + 1
        await client.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": file_uri,
                    "version": version,
                },
                # A change without a range replaces the complete document and
                # is valid for ALS's incremental synchronization capability.
                "contentChanges": [{"text": text}],
            },
        )
        client_open_files[file_uri] = _OpenFile(text=text, version=version)
        logger.debug(f"Updated file in ALS: {file_path}")
        return True

    project_source_created = client.is_new_project_source(path)
    if project_source_created:
        indexing_generation = await client.indexing_generation()
        # ALS explicitly reloads its Libadalang contexts for file-operation
        # notifications. A watched-file event alone only updates the current
        # context incrementally and leaves cross-unit name resolution stale.
        await client.send_notification(
            "workspace/didCreateFiles",
            {
                "files": [
                    {
                        "uri": file_uri,
                    }
                ]
            },
        )
        await client.send_notification(
            "workspace/didChangeWatchedFiles",
            {
                "changes": [
                    {
                        "uri": file_uri,
                        "type": 1,
                    }
                ]
            },
        )
        await client.send_request(
            "workspace/executeCommand",
            {
                "command": "als-reload-project",
                "arguments": [],
            },
        )
        client.remember_project_source(path)
        logger.debug(f"Announced new project source to ALS: {file_path}")

    # Determine language ID
    suffix = path.suffix.lower()
    if suffix in (".ads", ".adb"):
        language_id = "ada"
    elif suffix == ".gpr":
        language_id = "gpr"
    else:
        language_id = "ada"  # Default

    await client.send_notification(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": file_uri,
                "languageId": language_id,
                "version": 1,
                "text": text,
            }
        },
    )
    client_open_files[file_uri] = _OpenFile(text=text, version=1)
    logger.debug(f"Opened file in ALS: {file_path}")

    if project_source_created:
        if not await client.wait_for_indexing(
            after_generation=indexing_generation,
        ):
            raise LSPError(
                -1,
                f"Ada Language Server did not finish loading project source: {file_path}",
            )

    return True


async def _get_line_preview(file_path: str, line_0based: int) -> str:
    """Get a preview of a specific line from a file."""
    try:
        path = Path(file_path)
        if not path.exists():
            return ""

        lines = path.read_text().splitlines()
        if 0 <= line_0based < len(lines):
            return lines[line_0based].rstrip()
        return ""
    except Exception:
        return ""


def clear_open_files_cache() -> None:
    """Clear the open files cache (useful for testing)."""
    _open_files.clear()
    _open_file_locks.clear()
