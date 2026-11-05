"""Project intelligence tools for Ada MCP server.

Provides tools for:
- Project information from GPR files
- Call hierarchy (incoming/outgoing calls)
- Dependency graph analysis
"""

import re
from pathlib import Path
from typing import Any

from ada_mcp.als.client import ALSClient, LSPError

from ..utils.position import to_lsp_position
from ..utils.uri import file_to_uri, uri_to_file


def _to_dict(obj: Any) -> Any:
    """Recursively convert LSP objects to plain dictionaries."""
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    elif hasattr(obj, "to_dict"):
        # Has a to_dict method (like Position, Range)
        return obj.to_dict()
    elif hasattr(obj, "model_dump"):
        # Pydantic v2
        return obj.model_dump()
    elif hasattr(obj, "dict"):
        # Pydantic v1
        return obj.dict()
    elif hasattr(obj, "__dict__"):
        # Generic object with attributes
        return {k: _to_dict(v) for k, v in obj.__dict__.items()}
    else:
        return obj


async def _execute_als_command(als_client: ALSClient, command: str) -> Any:
    """Execute one of ALS's structured project-information commands."""
    return _to_dict(
        await als_client.send_request(
            "workspace/executeCommand",
            {"command": command, "arguments": []},
        )
    )


async def handle_project_info(als_client: ALSClient, gpr_file: str) -> dict[str, Any]:
    """Handle ada_project_info tool request.

    Args:
        als_client: Initialized ALS client for the requested project
        gpr_file: Path to the .gpr project file

    Returns:
        Project information evaluated by ALS/GPR
    """
    requested_project = Path(gpr_file).resolve()
    if not requested_project.is_file():
        raise FileNotFoundError(f"GPR project file does not exist: {requested_project}")

    try:
        project_info = await _execute_als_command(
            als_client,
            "als-project-view-information",
        )
    except LSPError as error:
        if error.code != -32603:
            raise
        return {
            "project_file": str(requested_project),
            "complete": False,
            "error": (
                "Ada Language Server could not evaluate the requested GPR "
                "project. Ensure that imported GPR projects, generated project "
                "files and required build dependencies are available."
            ),
            "reason": "project-load-failed",
            "lsp_code": error.code,
        }
    root_project_id = project_info.get("tree", {}).get("root-project", {}).get("id")
    root_project = next(
        (
            item.get("project")
            for item in project_info.get("projects", [])
            if item.get("project", {}).get("id") == root_project_id
        ),
        None,
    )
    if not root_project:
        raise RuntimeError("ALS did not return the root project view")

    loaded_project = Path(root_project.get("file-name", "")).resolve()
    if loaded_project != requested_project:
        raise RuntimeError(
            f"ALS loaded a different project: {loaded_project} instead of {requested_project}"
        )

    mains = await _execute_als_command(als_client, "als-mains")

    return {
        "project_file": str(loaded_project),
        "project_name": root_project.get("name"),
        "source_dirs": root_project.get("source-directories", []),
        "object_dir": root_project.get("object-directory"),
        "exec_dir": root_project.get("executable-directory"),
        "main_units": [Path(main).name for main in mains or []],
        "complete": True,
    }


async def handle_call_hierarchy(
    als_client: ALSClient,
    file: str,
    line: int,
    column: int,
    direction: str = "outgoing",
) -> dict[str, Any]:
    """Handle ada_call_hierarchy tool request.

    Args:
        als_client: ALS client instance
        file: Path to the source file
        line: Line number (1-based)
        column: Column number (1-based)
        direction: "outgoing", "incoming", or "both"

    Returns:
        Dictionary with call hierarchy information
    """
    file_uri = file_to_uri(file)
    lsp_pos = to_lsp_position(line, column)

    # First, prepare call hierarchy
    prepare_result = await als_client.send_request(
        "textDocument/prepareCallHierarchy",
        {"textDocument": {"uri": file_uri}, "position": lsp_pos},
    )

    if not prepare_result:
        return {"found": False, "outgoing_calls": [], "incoming_calls": []}

    # Get the first item (usually the symbol at the position)
    item = prepare_result[0] if isinstance(prepare_result, list) else prepare_result

    # Convert item to plain dict to avoid serialization issues
    item_dict = _to_dict(item)

    outgoing = []
    incoming = []

    # Get outgoing calls if requested
    if direction in ("outgoing", "both"):
        outgoing_result = await als_client.send_request(
            "callHierarchy/outgoingCalls", {"item": item_dict}
        )
        if outgoing_result:
            for call in outgoing_result:
                to_item = call.get("to", {})
                outgoing.append(
                    {
                        "name": to_item.get("name", ""),
                        "kind": to_item.get("kind", 0),
                        "file": uri_to_file(to_item.get("uri", "")),
                        "line": to_item.get("range", {}).get("start", {}).get("line", 0) + 1,
                        "column": to_item.get("range", {}).get("start", {}).get("character", 0) + 1,
                    }
                )

    # Get incoming calls if requested
    if direction in ("incoming", "both"):
        incoming_result = await als_client.send_request(
            "callHierarchy/incomingCalls", {"item": item_dict}
        )
        if incoming_result:
            for call in incoming_result:
                from_item = call.get("from", {})
                incoming.append(
                    {
                        "name": from_item.get("name", ""),
                        "kind": from_item.get("kind", 0),
                        "file": uri_to_file(from_item.get("uri", "")),
                        "line": from_item.get("range", {}).get("start", {}).get("line", 0) + 1,
                        "column": from_item.get("range", {}).get("start", {}).get("character", 0)
                        + 1,
                    }
                )

    return {
        "found": True,
        "symbol": item_dict.get("name", "") if isinstance(item_dict, dict) else str(item_dict),
        "outgoing_calls": outgoing,
        "incoming_calls": incoming,
        "outgoing_count": len(outgoing),
        "incoming_count": len(incoming),
    }


async def handle_dependency_graph(file: str) -> dict[str, Any]:
    """Handle ada_dependency_graph tool request.

    Parses 'with' clauses to build a dependency graph.

    Args:
        file: Path to the source file or directory

    Returns:
        Dictionary with dependency information
    """
    path = Path(file)

    if not path.exists():
        return {"dependencies": [], "package_count": 0}

    # Collect all .ads and .adb files
    ada_files = []
    if path.is_dir():
        ada_files = list(path.rglob("*.ads")) + list(path.rglob("*.adb"))
    else:
        ada_files = [path]

    # Parse dependencies from each file
    dependencies = []
    seen_packages = set()

    # Regex patterns for parsing
    pkg_pattern = r"(?:package|procedure|function)\s+(?:body\s+)?(\w+(?:\.\w+)*)"
    with_pattern = r"^\s*with\s+([\w.]+(?:\s*,\s*[\w.]+)*)\s*;"

    for ada_file in ada_files:
        content = ada_file.read_text()

        # Extract package or procedure name from this file
        pkg_match = re.search(pkg_pattern, content, re.IGNORECASE)
        if not pkg_match:
            continue

        package_name = pkg_match.group(1)
        seen_packages.add(package_name)

        # Find all 'with' clauses
        with_clauses = re.findall(with_pattern, content, re.MULTILINE | re.IGNORECASE)

        imported_packages = set()
        for clause in with_clauses:
            # Split by comma for multiple imports
            packages = [p.strip() for p in clause.split(",")]
            imported_packages.update(packages)

        if imported_packages:
            dependencies.append(
                {
                    "package": package_name,
                    "file": str(ada_file),
                    "depends_on": sorted(list(imported_packages)),
                }
            )

    return {"dependencies": dependencies, "package_count": len(seen_packages)}
