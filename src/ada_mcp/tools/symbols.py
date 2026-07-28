"""Symbol tools: document symbols and workspace symbol search."""

import logging
from pathlib import Path
from typing import Any

from ada_mcp.als.client import ALSClient, LSPError
from ada_mcp.als.types import SymbolKind
from ada_mcp.tools.navigation import (
    _ensure_file_open,
    _open_file_paths,
    _prune_deleted_open_files,
)
from ada_mcp.utils.uri import file_to_uri, uri_to_file

logger = logging.getLogger(__name__)


def _workspace_symbol_source_exists(item: dict[str, Any]) -> bool:
    """Reject stale ALS index entries whose source has been deleted."""
    uri = item.get("location", {}).get("uri")
    return not isinstance(uri, str) or Path(uri_to_file(uri)).exists()


async def handle_document_symbols(
    client: ALSClient,
    file: str,
) -> dict[str, Any]:
    """
    Get all symbols defined in an Ada file.

    Args:
        client: ALS client instance
        file: Absolute path to Ada file

    Returns:
        Dict with hierarchical symbol list
    """
    file_uri = file_to_uri(file)

    synchronized = await _ensure_file_open(client, file)
    if synchronized is None:
        return {
            "symbols": [],
            "complete": False,
            "error": f"File not found: {file}",
            "context": {"file": file},
        }

    try:
        result = await client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": file_uri}},
        )
    except LSPError as e:
        logger.error(f"LSP error in document_symbols: {e}")
        return {
            "symbols": [],
            "error": e.message,
            "context": {"file": file},
        }

    if not result:
        return {"symbols": []}

    # ALS returns either DocumentSymbol[] (hierarchical) or SymbolInformation[] (flat)
    symbols = []
    for item in result:
        if "location" in item:
            # SymbolInformation format (flat)
            symbols.append(_convert_symbol_information(item))
        else:
            # DocumentSymbol format (hierarchical)
            symbols.append(_convert_document_symbol(item))

    return {"symbols": symbols}


async def handle_workspace_symbols(
    client: ALSClient,
    query: str,
    kind: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """
    Search for symbols by name across the workspace.

    Args:
        client: ALS client instance
        query: Symbol name or pattern to search for
        kind: Filter by kind - "package", "procedure", "function", "type", "variable", "all"
        limit: Maximum number of results

    Returns:
        Dict with matching symbols
    """
    await _prune_deleted_open_files(client)

    if not await client.wait_for_indexing():
        return {
            "symbols": [],
            "count": 0,
            "complete": False,
            "error": "Ada Language Server project indexing did not complete",
            "context": {"query": query, "kind": kind},
        }

    try:
        workspace_result = await client.send_request(
            "workspace/symbol",
            {"query": query},
        )
    except LSPError as e:
        logger.error(f"LSP error in workspace_symbols: {e}")
        return {
            "symbols": [],
            "count": 0,
            "complete": False,
            "error": e.message,
            "context": {"query": query, "kind": kind},
        }

    kind_filter = _get_kind_filter(kind)
    candidates = [
        _convert_symbol_information(item)
        for item in workspace_result or []
        if _workspace_symbol_source_exists(item)
        and (not kind_filter or item.get("kind", 0) in kind_filter)
    ]

    # The pinned ALS removes open documents from workspace/symbol results.
    # Merge their live document symbols so opening a source for an earlier
    # semantic operation cannot make it disappear from a later workspace
    # search.
    for file in _open_file_paths(client):
        if not file.lower().endswith((".ads", ".adb")):
            continue

        try:
            document_result = await client.send_request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": file_to_uri(file)}},
            )
        except LSPError as e:
            logger.error(f"LSP error reading open document symbols: {e}")
            return {
                "symbols": [],
                "count": 0,
                "complete": False,
                "error": e.message,
                "context": {
                    "query": query,
                    "kind": kind,
                    "file": file,
                },
            }

        for item in document_result or []:
            candidates.extend(
                _flatten_document_symbols(
                    item,
                    file=file,
                    query=query,
                    kind_filter=kind_filter,
                )
            )

    symbols = []
    seen = set()
    for symbol in candidates:
        # ALS may retain a deleted source in its workspace index even after a
        # project reload, and a concurrent deletion can also occur after the
        # raw-result filter above. Apply the filesystem boundary to the merged
        # workspace and live-document candidates as the final completeness
        # check.
        if symbol["file"] and not Path(symbol["file"]).exists():
            continue

        identity = (
            symbol["name"],
            symbol["kind"],
            symbol["file"],
            symbol["line"],
            symbol["column"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        symbols.append(symbol)

    truncated = len(symbols) > limit
    symbols = symbols[:limit]

    return {
        "symbols": symbols,
        "count": len(symbols),
        "truncated": truncated,
        "complete": True,
    }


def _flatten_document_symbols(
    item: dict[str, Any],
    file: str,
    query: str,
    kind_filter: set[int] | None,
) -> list[dict[str, Any]]:
    """Flatten matching symbols from one open document."""
    symbols = []
    symbol_kind = item.get("kind", 0)
    name = item.get("name", "")
    if (not kind_filter or symbol_kind in kind_filter) and query.casefold() in name.casefold():
        start = item.get("selectionRange", item.get("range", {})).get(
            "start",
            {},
        )
        symbols.append(
            {
                "name": name,
                "kind": _kind_to_string(symbol_kind),
                "file": file,
                "line": start.get("line", 0) + 1,
                "column": start.get("character", 0) + 1,
                "containerName": "",
            }
        )

    for child in item.get("children", []):
        symbols.extend(
            _flatten_document_symbols(
                child,
                file=file,
                query=query,
                kind_filter=kind_filter,
            )
        )

    return symbols


def _convert_document_symbol(item: dict[str, Any]) -> dict[str, Any]:
    """Convert LSP DocumentSymbol to our format."""
    range_data = item.get("range", {})
    selection_range = item.get("selectionRange", range_data)
    start = selection_range.get("start", {})

    symbol = {
        "name": item.get("name", ""),
        "kind": _kind_to_string(item.get("kind", 0)),
        "line": start.get("line", 0) + 1,
        "column": start.get("character", 0) + 1,
        "range": {
            "start": range_data.get("start", {}).get("line", 0) + 1,
            "end": range_data.get("end", {}).get("line", 0) + 1,
        },
    }

    # Add detail if present
    if "detail" in item:
        symbol["detail"] = item["detail"]

    # Recursively convert children
    children = item.get("children", [])
    if children:
        symbol["children"] = [_convert_document_symbol(child) for child in children]

    return symbol


def _convert_symbol_information(item: dict[str, Any]) -> dict[str, Any]:
    """Convert LSP SymbolInformation to our format."""
    location = item.get("location", {})
    location_uri = location.get("uri", "")
    loc_range = location.get("range", {})
    start = loc_range.get("start", {})

    return {
        "name": item.get("name", ""),
        "kind": _kind_to_string(item.get("kind", 0)),
        "file": uri_to_file(location_uri) if location_uri else "",
        "line": start.get("line", 0) + 1,
        "column": start.get("character", 0) + 1,
        "containerName": item.get("containerName", ""),
    }


def _get_kind_filter(kind: str) -> set[int] | None:
    """Get set of SymbolKind values to include based on filter string."""
    if kind == "all":
        return None

    kind_map = {
        "package": {SymbolKind.PACKAGE, SymbolKind.MODULE, SymbolKind.NAMESPACE},
        "procedure": {SymbolKind.FUNCTION, SymbolKind.METHOD},  # Ada procedures map to functions
        "function": {SymbolKind.FUNCTION, SymbolKind.METHOD},
        "type": {SymbolKind.CLASS, SymbolKind.STRUCT, SymbolKind.ENUM, SymbolKind.INTERFACE},
        "variable": {SymbolKind.VARIABLE, SymbolKind.CONSTANT, SymbolKind.FIELD},
        "constant": {SymbolKind.CONSTANT},
    }

    return kind_map.get(kind.lower())


def _kind_to_string(kind: int) -> str:
    """Convert LSP SymbolKind to human-readable string."""
    kind_names = {
        SymbolKind.FILE: "file",
        SymbolKind.MODULE: "module",
        SymbolKind.NAMESPACE: "namespace",
        SymbolKind.PACKAGE: "package",
        SymbolKind.CLASS: "class",
        SymbolKind.METHOD: "method",
        SymbolKind.PROPERTY: "property",
        SymbolKind.FIELD: "field",
        SymbolKind.CONSTRUCTOR: "constructor",
        SymbolKind.ENUM: "enum",
        SymbolKind.INTERFACE: "interface",
        SymbolKind.FUNCTION: "function",
        SymbolKind.VARIABLE: "variable",
        SymbolKind.CONSTANT: "constant",
        SymbolKind.STRING: "string",
        SymbolKind.NUMBER: "number",
        SymbolKind.BOOLEAN: "boolean",
        SymbolKind.ARRAY: "array",
        SymbolKind.OBJECT: "object",
        SymbolKind.KEY: "key",
        SymbolKind.NULL: "null",
        SymbolKind.ENUM_MEMBER: "enumMember",
        SymbolKind.STRUCT: "struct",
        SymbolKind.EVENT: "event",
        SymbolKind.OPERATOR: "operator",
        SymbolKind.TYPE_PARAMETER: "typeParameter",
    }
    return kind_names.get(kind, f"unknown({kind})")
