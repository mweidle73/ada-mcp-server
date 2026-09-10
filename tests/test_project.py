"""Unit tests for Phase 3: Project Intelligence tools."""

from pathlib import Path
from unittest.mock import AsyncMock, call

import pytest

from ada_mcp.als.client import LSPError
from ada_mcp.tools.project import (
    handle_call_hierarchy,
    handle_dependency_graph,
    handle_project_info,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_gpr_path():
    """Path to sample GPR file."""
    return Path(__file__).parent / "fixtures" / "sample_project" / "sample.gpr"


@pytest.fixture
def sample_ada_file():
    """Path to sample Ada file."""
    return Path(__file__).parent / "fixtures" / "sample_project" / "src" / "main.adb"


@pytest.fixture
def mock_als_client():
    """Create a mock ALS client."""
    client = AsyncMock()
    client.send_request = AsyncMock()
    return client


# ============================================================================
# ada_project_info Tests (Task 3.2)
# ============================================================================

class TestProjectInfo:
    """Tests for ada_project_info tool."""

    @pytest.mark.asyncio
    async def test_project_info_uses_evaluated_als_view(
        self,
        sample_gpr_path,
        mock_als_client,
    ):
        """Test project information from ALS's evaluated GPR view."""
        project_root = sample_gpr_path.parent.resolve()
        root_project = {
            "id": "sample",
            "name": "Sample",
            "file-name": str(sample_gpr_path.resolve()),
            "source-directories": [
                str(project_root / "src"),
                str(project_root / "generated"),
            ],
            "object-directory": str(project_root / "obj/debug"),
            "executable-directory": str(project_root / "bin/debug"),
        }
        mock_als_client.send_request.side_effect = [
            {
                "tree": {"root-project": {"id": "sample"}},
                "projects": [{"project": root_project}],
            },
            [
                str(project_root / "src/main.adb"),
                str(project_root / "tests/tester.adb"),
            ],
        ]

        result = await handle_project_info(
            mock_als_client,
            str(sample_gpr_path),
        )

        assert result["project_file"] == str(sample_gpr_path.resolve())
        assert result["project_name"] == "Sample"
        assert result["source_dirs"] == root_project["source-directories"]
        assert all(Path(d).is_absolute() for d in result["source_dirs"])
        assert result["object_dir"] == str(project_root / "obj/debug")
        assert result["exec_dir"] == str(project_root / "bin/debug")
        assert result["main_units"] == ["main.adb", "tester.adb"]
        assert result["complete"] is True
        assert mock_als_client.send_request.await_args_list == [
            call(
                "workspace/executeCommand",
                {
                    "command": "als-project-view-information",
                    "arguments": [],
                },
            ),
            call(
                "workspace/executeCommand",
                {"command": "als-mains", "arguments": []},
            ),
        ]

    @pytest.mark.asyncio
    async def test_project_info_rejects_wrong_loaded_project(
        self,
        sample_gpr_path,
        mock_als_client,
    ):
        """Test that stale or ignored ALS project configuration fails loudly."""
        mock_als_client.send_request.return_value = {
            "tree": {"root-project": {"id": "other"}},
            "projects": [
                {
                    "project": {
                        "id": "other",
                        "file-name": "/tmp/other.gpr",
                    }
                }
            ],
        }

        with pytest.raises(RuntimeError, match="loaded a different project"):
            await handle_project_info(
                mock_als_client,
                str(sample_gpr_path),
            )

    @pytest.mark.asyncio
    async def test_project_info_nonexistent(self, mock_als_client):
        """Test project info for non-existent file."""
        with pytest.raises(FileNotFoundError):
            await handle_project_info(
                mock_als_client,
                "/nonexistent/project.gpr",
            )
        mock_als_client.send_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_project_info_calibrates_als_project_load_failure(
        self,
        sample_gpr_path,
        mock_als_client,
    ):
        """An ALS project-view failure must not expose its internal backtrace."""
        mock_als_client.send_request.side_effect = LSPError(
            -32603,
            "Exception: raised CONSTRAINT_ERROR\n/internal/als/backtrace",
        )

        result = await handle_project_info(
            mock_als_client,
            str(sample_gpr_path),
        )

        assert result == {
            "project_file": str(sample_gpr_path.resolve()),
            "complete": False,
            "error": (
                "Ada Language Server could not evaluate the requested GPR "
                "project. Ensure that imported GPR projects, generated project "
                "files and required build dependencies are available."
            ),
            "reason": "project-load-failed",
            "lsp_code": -32603,
        }
        assert "backtrace" not in result["error"]

    @pytest.mark.asyncio
    async def test_project_info_preserves_transport_failure(
        self,
        sample_gpr_path,
        mock_als_client,
    ):
        """A transport failure is not misreported as a broken GPR closure."""
        mock_als_client.send_request.side_effect = LSPError(
            -1,
            "ALS connection closed",
        )

        with pytest.raises(LSPError, match="ALS connection closed"):
            await handle_project_info(
                mock_als_client,
                str(sample_gpr_path),
            )


# ============================================================================
# ada_call_hierarchy Tests (Task 3.3 & 3.4)
# ============================================================================

class TestCallHierarchy:
    """Tests for ada_call_hierarchy tool."""
    
    @pytest.mark.asyncio
    async def test_call_hierarchy_outgoing(self, mock_als_client):
        """Test outgoing call hierarchy."""
        # Mock prepare call hierarchy
        mock_als_client.send_request.side_effect = [
            # prepareCallHierarchy response
            [{
                "name": "Main",
                "kind": 12,
                "uri": "file:///test/main.adb",
                "range": {"start": {"line": 3, "character": 10}}
            }],
            # outgoingCalls response
            [{
                "to": {
                    "name": "Utils.Add",
                    "kind": 12,
                    "uri": "file:///test/utils.adb",
                    "range": {"start": {"line": 4, "character": 12}}
                }
            }]
        ]
        
        result = await handle_call_hierarchy(
            mock_als_client,
            "/test/main.adb",
            line=4,
            column=11,
            direction="outgoing"
        )
        
        assert result["found"] is True
        assert result["symbol"] == "Main"
        assert len(result["outgoing_calls"]) == 1
        assert result["outgoing_calls"][0]["name"] == "Utils.Add"
        assert result["outgoing_count"] == 1
        assert len(result["incoming_calls"]) == 0
    
    @pytest.mark.asyncio
    async def test_call_hierarchy_incoming(self, mock_als_client):
        """Test incoming call hierarchy."""
        mock_als_client.send_request.side_effect = [
            # prepareCallHierarchy response
            [{
                "name": "Add",
                "kind": 12,
                "uri": "file:///test/utils.adb",
                "range": {"start": {"line": 4, "character": 12}}
            }],
            # incomingCalls response
            [{
                "from": {
                    "name": "Main",
                    "kind": 12,
                    "uri": "file:///test/main.adb",
                    "range": {"start": {"line": 5, "character": 4}}
                }
            }]
        ]
        
        result = await handle_call_hierarchy(
            mock_als_client,
            "/test/utils.adb",
            line=5,
            column=13,
            direction="incoming"
        )
        
        assert result["found"] is True
        assert len(result["incoming_calls"]) == 1
        assert result["incoming_calls"][0]["name"] == "Main"
        assert result["incoming_count"] == 1
        assert len(result["outgoing_calls"]) == 0
    
    @pytest.mark.asyncio
    async def test_call_hierarchy_both(self, mock_als_client):
        """Test both incoming and outgoing calls."""
        mock_als_client.send_request.side_effect = [
            # prepareCallHierarchy response
            [{
                "name": "Process",
                "kind": 12,
                "uri": "file:///test/process.adb",
                "range": {"start": {"line": 10, "character": 12}}
            }],
            # outgoingCalls response
            [{"to": {"name": "Helper", "kind": 12, "uri": "file:///test/helper.adb", "range": {"start": {"line": 5, "character": 4}}}}],
            # incomingCalls response
            [{"from": {"name": "Main", "kind": 12, "uri": "file:///test/main.adb", "range": {"start": {"line": 8, "character": 4}}}}]
        ]
        
        result = await handle_call_hierarchy(
            mock_als_client,
            "/test/process.adb",
            line=11,
            column=13,
            direction="both"
        )
        
        assert result["found"] is True
        assert len(result["outgoing_calls"]) == 1
        assert len(result["incoming_calls"]) == 1
        assert result["outgoing_count"] == 1
        assert result["incoming_count"] == 1
    
    @pytest.mark.asyncio
    async def test_call_hierarchy_not_found(self, mock_als_client):
        """Test call hierarchy when symbol not found."""
        mock_als_client.send_request.return_value = None
        
        result = await handle_call_hierarchy(
            mock_als_client,
            "/test/main.adb",
            line=1,
            column=1,
            direction="outgoing"
        )
        
        assert result["found"] is False
        assert result["outgoing_calls"] == []
        assert result["incoming_calls"] == []


# ============================================================================
# ada_dependency_graph Tests (Task 3.5)
# ============================================================================

class TestDependencyGraph:
    """Tests for ada_dependency_graph tool."""
    
    @pytest.mark.asyncio
    async def test_dependency_graph_single_file(self, tmp_path):
        """Test dependency graph for a single file."""
        ada_file = tmp_path / "utils.ads"
        ada_file.write_text("""
with Ada.Text_IO;
with Ada.Strings;

package Utils is
   function Add (A, B : Integer) return Integer;
end Utils;
""")
        
        result = await handle_dependency_graph(str(ada_file))
        
        assert result["package_count"] == 1
        assert len(result["dependencies"]) == 1
        dep = result["dependencies"][0]
        assert dep["package"] == "Utils"
        assert "Ada.Text_IO" in dep["depends_on"]
        assert "Ada.Strings" in dep["depends_on"]
    
    @pytest.mark.asyncio
    async def test_dependency_graph_directory(self, sample_ada_file):
        """Test dependency graph for a directory."""
        src_dir = sample_ada_file.parent
        
        result = await handle_dependency_graph(str(src_dir))
        
        assert result["package_count"] >= 1
        assert len(result["dependencies"]) >= 1
    
    @pytest.mark.asyncio
    async def test_dependency_graph_multiple_with(self, tmp_path):
        """Test parsing multiple packages in one with clause."""
        ada_file = tmp_path / "main.adb"
        ada_file.write_text("""
with Ada.Text_IO, Ada.Strings, Utils;

procedure Main is
begin
   null;
end Main;
""")
        
        result = await handle_dependency_graph(str(ada_file))
        
        assert len(result["dependencies"]) == 1
        deps = result["dependencies"][0]["depends_on"]
        assert "Ada.Text_IO" in deps
        assert "Ada.Strings" in deps
        assert "Utils" in deps
    
    @pytest.mark.asyncio
    async def test_dependency_graph_nonexistent(self):
        """Test dependency graph for non-existent path."""
        result = await handle_dependency_graph("/nonexistent/path")
        
        assert result["dependencies"] == []
        assert result["package_count"] == 0
    
    @pytest.mark.asyncio
    async def test_dependency_graph_package_body(self, tmp_path):
        """Test dependency graph includes package bodies."""
        ada_file = tmp_path / "utils.adb"
        ada_file.write_text("""
with Ada.Text_IO;

package body Utils is
   function Add (A, B : Integer) return Integer is
   begin
      return A + B;
   end Add;
end Utils;
""")
        
        result = await handle_dependency_graph(str(ada_file))
        
        assert result["package_count"] == 1
        assert len(result["dependencies"]) == 1
        assert result["dependencies"][0]["package"] == "Utils"
        assert "Ada.Text_IO" in result["dependencies"][0]["depends_on"]
