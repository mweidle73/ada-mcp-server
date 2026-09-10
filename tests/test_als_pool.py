"""Tests for the ALS pool functionality."""

import asyncio
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from ada_mcp.server import ALSInstance, ALSPool


class TestALSInstance:
    """Tests for ALSInstance dataclass."""

    def test_instance_creation(self):
        """Test creating an ALS instance."""
        mock_client = MagicMock()
        mock_monitor = MagicMock()
        project_root = Path("/test/project")

        instance = ALSInstance(
            client=mock_client,
            monitor=mock_monitor,
            project_root=project_root,
            project_file=None,
            last_used=12345.0,
            lock=asyncio.Lock(),
        )

        assert instance.client is mock_client
        assert instance.monitor is mock_monitor
        assert instance.project_root == project_root
        assert instance.project_file is None
        assert instance.last_used == 12345.0


class TestALSPool:
    """Tests for ALSPool class."""

    def test_pool_creation(self):
        """Test creating a pool with default settings."""
        pool = ALSPool()
        assert pool.max_instances == 3
        assert pool.idle_timeout == 300.0
        assert len(pool._instances) == 0

    def test_pool_custom_settings(self):
        """Test creating a pool with custom settings."""
        pool = ALSPool(max_instances=5, idle_timeout=600.0)
        assert pool.max_instances == 5
        assert pool.idle_timeout == 600.0

    def test_get_stats_empty(self):
        """Test stats on empty pool."""
        pool = ALSPool()
        stats = pool.get_stats()
        assert stats["active_instances"] == 0
        assert stats["max_instances"] == 3
        assert stats["projects"] == []

    @pytest.mark.asyncio
    async def test_get_client_creates_instance(self):
        """Test that get_client creates a new ALS instance."""
        pool = ALSPool()

        mock_client = MagicMock()
        mock_client.is_running = True
        mock_monitor = MagicMock()

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                return_value=(mock_client, mock_monitor),
            ),
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
        ):
            client = await pool.get_client("/test/project/src/main.adb")

            assert client is mock_client
            assert len(pool._instances) == 1
            assert (Path("/test/project"), None) in pool._instances

    @pytest.mark.asyncio
    async def test_get_client_reuses_instance(self):
        """Test that get_client reuses existing instances."""
        pool = ALSPool()

        mock_client = MagicMock()
        mock_client.is_running = True
        mock_monitor = MagicMock()

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                return_value=(mock_client, mock_monitor),
            ) as mock_start,
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
        ):
            # First call creates instance
            client1 = await pool.get_client("/test/project/src/main.adb")
            # Second call should reuse
            client2 = await pool.get_client("/test/project/src/utils.ads")

            assert client1 is client2
            # start_als_with_monitoring should only be called once
            assert mock_start.call_count == 1

    @pytest.mark.asyncio
    async def test_get_client_selects_explicit_gpr_for_following_sources(self):
        """An explicit GPR selects the project view reused by source tools."""
        pool = ALSPool()
        client = MagicMock()
        client.is_running = True
        monitor = MagicMock()
        project_root = Path("/test/project")
        project_file = project_root / "spawn_manager.gpr"

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                return_value=(client, monitor),
            ) as mock_start,
            patch(
                "ada_mcp.server.find_project_root",
                return_value=project_root,
            ),
        ):
            selected = await pool.get_client(
                str(project_file),
                gpr_file=project_file,
            )
            await pool.select_client(selected)
            reused = await pool.get_client("/test/project/src/spawn-pool.adb")

        assert selected is client
        assert reused is client
        mock_start.assert_awaited_once_with(
            project_root,
            gpr_file=project_file,
            on_restart=ANY,
        )

    @pytest.mark.asyncio
    async def test_explicit_gpr_does_not_reuse_auto_detected_project(self):
        """A requested GPR must not inherit another view from the same root."""
        pool = ALSPool()
        clients = [MagicMock(), MagicMock()]
        for client in clients:
            client.is_running = True
        monitor = MagicMock()
        project_root = Path("/test/project")
        project_file = project_root / "spawn_manager.gpr"

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                side_effect=[(clients[0], monitor), (clients[1], monitor)],
            ) as mock_start,
            patch(
                "ada_mcp.server.find_project_root",
                return_value=project_root,
            ),
        ):
            automatic = await pool.get_client("/test/project/src/other.adb")
            selected = await pool.get_client(
                str(project_file),
                gpr_file=project_file,
            )
            await pool.select_client(selected)
            reused = await pool.get_client("/test/project/src/spawn-pool.adb")

        assert automatic is clients[0]
        assert selected is clients[1]
        assert reused is clients[1]
        assert mock_start.call_count == 2

    @pytest.mark.asyncio
    async def test_explicit_gpr_selection_survives_lru_eviction(self):
        """Reload an evicted root with its previously selected GPR file."""
        pool = ALSPool(max_instances=1)
        clients = [MagicMock(), MagicMock(), MagicMock()]
        for client in clients:
            client.is_running = True
        monitor = MagicMock()
        selected_root = Path("/selected")
        selected_gpr = selected_root / "spawn_manager.gpr"

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                side_effect=[
                    (clients[0], monitor),
                    (clients[1], monitor),
                    (clients[2], monitor),
                ],
            ) as mock_start,
            patch(
                "ada_mcp.server.find_project_root",
                side_effect=[selected_root, Path("/other"), selected_root],
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ),
        ):
            selected = await pool.get_client(str(selected_gpr), gpr_file=selected_gpr)
            await pool.select_client(selected)
            await pool.get_client("/other/src/main.adb")
            reloaded = await pool.get_client("/selected/src/spawn-pool.adb")

        assert reloaded is clients[2]
        assert mock_start.await_args.kwargs["gpr_file"] == selected_gpr

    @pytest.mark.asyncio
    async def test_rejected_gpr_preserves_previous_selection(self):
        """Discarding a new view keeps the last validated project selected."""
        pool = ALSPool()
        clients = [MagicMock(), MagicMock()]
        for client in clients:
            client.is_running = True
        monitor = MagicMock()
        project_root = Path("/test/project")
        first_gpr = project_root / "first.gpr"
        rejected_gpr = project_root / "rejected.gpr"

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                side_effect=[(clients[0], monitor), (clients[1], monitor)],
            ),
            patch(
                "ada_mcp.server.find_project_root",
                return_value=project_root,
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ),
        ):
            selected = await pool.get_client(str(first_gpr), gpr_file=first_gpr)
            await pool.select_client(selected)
            rejected = await pool.get_client(
                str(rejected_gpr),
                gpr_file=rejected_gpr,
            )
            await pool.discard_client(str(rejected_gpr), rejected)
            reused = await pool.get_client("/test/project/src/main.adb")

        assert reused is clients[0]

    @pytest.mark.asyncio
    async def test_discard_client_reloads_failed_project_view(self):
        """A rejected cached client is replaced on the next request."""
        pool = ALSPool()
        clients = [MagicMock(), MagicMock()]
        for client in clients:
            client.is_running = True
        monitor = MagicMock()

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                side_effect=[(clients[0], monitor), (clients[1], monitor)],
            ) as mock_start,
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ) as mock_shutdown,
        ):
            first = await pool.get_client("/test/project/abuild.gpr")
            await pool.discard_client("/test/project/abuild.gpr", first)
            second = await pool.get_client("/test/project/abuild.gpr")

        assert first is clients[0]
        assert second is clients[1]
        assert mock_start.call_count == 2
        mock_shutdown.assert_awaited_once_with(clients[0], monitor)

    @pytest.mark.asyncio
    async def test_discard_client_preserves_replacement(self):
        """A stale request cannot discard a newer monitor replacement."""
        pool = ALSPool()
        old_client = MagicMock()
        new_client = MagicMock()
        old_client.is_running = True
        new_client.is_running = True
        monitor = MagicMock()

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                return_value=(old_client, monitor),
            ),
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ) as mock_shutdown,
        ):
            await pool.get_client("/test/project/abuild.gpr")
            pool._instances[(Path("/test/project"), None)].client = new_client
            await pool.discard_client("/test/project/abuild.gpr", old_client)

        assert pool._instances[(Path("/test/project"), None)].client is new_client
        mock_shutdown.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_client_different_projects(self):
        """Test that different projects get different instances."""
        pool = ALSPool()

        mock_client1 = MagicMock()
        mock_client1.is_running = True
        mock_client2 = MagicMock()
        mock_client2.is_running = True
        mock_monitor = MagicMock()

        call_count = 0

        async def mock_start(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (mock_client1, mock_monitor)
            return (mock_client2, mock_monitor)

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                side_effect=mock_start,
            ),
            patch(
                "ada_mcp.server.find_project_root",
                side_effect=lambda p: Path(str(p).rsplit("/src", 1)[0]),
            ),
        ):
            client1 = await pool.get_client("/project1/src/main.adb")
            client2 = await pool.get_client("/project2/src/main.adb")

            assert client1 is not client2
            assert len(pool._instances) == 2

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Test that LRU eviction works when pool is full."""
        pool = ALSPool(max_instances=2)

        clients = [MagicMock() for _ in range(3)]
        for c in clients:
            c.is_running = True
        mock_monitor = MagicMock()

        call_count = 0

        async def mock_start(*args, **kwargs):
            nonlocal call_count
            result = (clients[call_count], mock_monitor)
            call_count += 1
            return result

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                side_effect=mock_start,
            ),
            patch(
                "ada_mcp.server.find_project_root",
                side_effect=lambda p: Path(str(p).rsplit("/src", 1)[0]),
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ) as mock_shutdown,
        ):
            # Fill the pool
            await pool.get_client("/project1/src/main.adb")
            await pool.get_client("/project2/src/main.adb")

            assert len(pool._instances) == 2

            # Add a third - should evict oldest
            await pool.get_client("/project3/src/main.adb")

            # Should still have only 2 instances
            assert len(pool._instances) == 2
            # Shutdown should have been called for eviction
            assert mock_shutdown.called

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        """Test shutting down all instances."""
        pool = ALSPool()

        mock_client = MagicMock()
        mock_client.is_running = True
        mock_monitor = MagicMock()

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                new_callable=AsyncMock,
                return_value=(mock_client, mock_monitor),
            ),
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
            patch(
                "ada_mcp.server.shutdown_als",
                new_callable=AsyncMock,
            ) as mock_shutdown,
        ):
            await pool.get_client("/test/project/src/main.adb")
            assert len(pool._instances) == 1

            await pool.shutdown_all()

            assert len(pool._instances) == 0
            assert mock_shutdown.called

    @pytest.mark.asyncio
    async def test_dead_instance_removed(self):
        """Test that dead instances are removed and recreated."""
        pool = ALSPool()

        mock_client1 = MagicMock()
        mock_client1.is_running = True
        mock_client2 = MagicMock()
        mock_client2.is_running = True
        mock_monitor = MagicMock()

        call_count = 0

        async def mock_start(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (mock_client1, mock_monitor)
            return (mock_client2, mock_monitor)

        with (
            patch(
                "ada_mcp.server.start_als_with_monitoring",
                side_effect=mock_start,
            ),
            patch(
                "ada_mcp.server.find_project_root",
                return_value=Path("/test/project"),
            ),
        ):
            # First call creates instance
            client1 = await pool.get_client("/test/project/src/main.adb")
            assert client1 is mock_client1

            # Simulate client dying
            mock_client1.is_running = False

            # Next call should create new instance
            client2 = await pool.get_client("/test/project/src/main.adb")
            assert client2 is mock_client2
            assert call_count == 2
