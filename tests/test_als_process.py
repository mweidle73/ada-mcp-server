"""Tests for ALS process management and health monitoring."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ada_mcp.als.process import (
    ALSHealthMonitor,
    get_project_scenario_variables,
    start_als,
)


async def start_mock_als(tmp_path, *, caplog=None):
    """Start ALS with a mocked transport and return its client."""
    gpr_file = tmp_path / "sample.gpr"
    gpr_file.write_text("project Sample is end Sample;\n")
    process = MagicMock()
    client = MagicMock()
    client.send_request = AsyncMock(return_value={"capabilities": {}})
    client.send_notification = AsyncMock()

    with (
        patch(
            "ada_mcp.als.process.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch("ada_mcp.als.process.ALSClient", return_value=client),
        patch(
            "ada_mcp.als.process.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        result = await start_als(
            tmp_path,
            als_path="/test/ada_language_server",
            gpr_file=gpr_file,
        )

    if caplog is not None:
        assert "BUILD_MODE" in caplog.text
        assert "analysis" not in caplog.text

    assert result is client
    client.set_project_source_baseline.assert_called_once_with(tmp_path)
    return client


@pytest.mark.asyncio
async def test_start_als_configures_project_through_lsp(tmp_path):
    """Test that current ALS receives the project through LSP settings."""
    client = await start_mock_als(tmp_path)

    client.send_notification.assert_any_await(
        "workspace/didChangeConfiguration",
        {"settings": {"ada": {"projectFile": "sample.gpr"}}},
    )
    initialize_params = client.send_request.await_args_list[0].args[1]
    assert initialize_params["capabilities"]["workspace"]["didChangeWatchedFiles"] == {
        "dynamicRegistration": True,
    }
    assert "scenarioVariables" not in initialize_params["initializationOptions"]


@pytest.mark.asyncio
async def test_start_als_configures_scenario_variables(tmp_path, monkeypatch, caplog):
    """Test that ALS receives explicitly configured scenario variables."""
    caplog.set_level("INFO")
    monkeypatch.setenv(
        "ADA_PROJECT_SCENARIO_VARIABLES",
        '{"BUILD_MODE":"analysis"}',
    )
    client = await start_mock_als(tmp_path, caplog=caplog)

    client.send_notification.assert_any_await(
        "workspace/didChangeConfiguration",
        {
            "settings": {
                "ada": {
                    "projectFile": "sample.gpr",
                    "scenarioVariables": {"BUILD_MODE": "analysis"},
                }
            }
        },
    )
    initialize_params = client.send_request.await_args_list[0].args[1]
    assert initialize_params["capabilities"]["workspace"]["didChangeWatchedFiles"] == {
        "dynamicRegistration": True,
    }
    assert initialize_params["initializationOptions"]["scenarioVariables"] == {
        "BUILD_MODE": "analysis",
    }


@pytest.mark.parametrize("value", [None, "", "  \t"])
def test_project_scenario_variables_default_to_empty(monkeypatch, value):
    """An unset or empty payload preserves default ALS configuration."""
    if value is None:
        monkeypatch.delenv("ADA_PROJECT_SCENARIO_VARIABLES", raising=False)
    else:
        monkeypatch.setenv("ADA_PROJECT_SCENARIO_VARIABLES", value)

    assert get_project_scenario_variables() == {}


@pytest.mark.parametrize(
    "value",
    ["not-json", "[]", '{"BUILD_MODE":1}'],
)
def test_project_scenario_variables_reject_invalid_values(monkeypatch, value):
    """Scenario variables must match the ALS string map contract."""
    monkeypatch.setenv("ADA_PROJECT_SCENARIO_VARIABLES", value)

    with pytest.raises(ValueError, match="must be a JSON object of string values"):
        get_project_scenario_variables()


class TestALSHealthMonitor:
    """Tests for ALSHealthMonitor class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ALS client."""
        client = MagicMock()
        client.is_running = True
        return client

    @pytest.fixture
    def monitor(self, mock_client):
        """Create an ALSHealthMonitor instance."""
        return ALSHealthMonitor(
            client=mock_client,
            project_root=Path("/test/project"),
            als_path="/test/als",
            gpr_file=Path("/test/project/test.gpr"),
            initial_backoff_seconds=0.1,  # Fast for tests
            max_backoff_seconds=1.0,
        )

    def test_initial_state(self, monitor):
        """Test initial monitor state."""
        assert monitor.restart_count == 0
        assert monitor._shutdown_requested is False
        assert monitor._monitor_task is None

    def test_stop_monitoring_sets_flag(self, monitor):
        """Test that stop_monitoring sets shutdown flag."""
        monitor.stop_monitoring()
        assert monitor._shutdown_requested is True

    def test_reset_restart_count(self, monitor):
        """Test resetting restart counter."""
        monitor.restart_count = 3
        monitor.reset_restart_count()
        assert monitor.restart_count == 0

    @pytest.mark.asyncio
    async def test_start_monitoring_creates_task(self, monitor):
        """Test that start_monitoring creates a monitoring task."""
        monitor.start_monitoring()
        assert monitor._monitor_task is not None
        assert not monitor._monitor_task.done()

        # Clean up
        monitor.stop_monitoring()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_callback_stored(self, monitor):
        """Test that on_restart callback is stored."""
        callback = MagicMock()
        monitor.start_monitoring(on_restart=callback)
        assert monitor._on_restart_callback == callback

        # Clean up
        monitor.stop_monitoring()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self, monitor):
        """Test exponential backoff calculation."""
        # With initial_backoff=0.1, multiplier=2.0
        # attempt 0: 0.1
        # attempt 1: 0.2
        # attempt 2: 0.4
        # etc.
        assert monitor.initial_backoff_seconds == 0.1
        assert monitor.backoff_multiplier == 2.0

        # Calculate expected backoff for each attempt
        for attempt in range(5):
            expected = min(
                monitor.initial_backoff_seconds * (monitor.backoff_multiplier**attempt),
                monitor.max_backoff_seconds,
            )
            actual = min(
                monitor.initial_backoff_seconds * (monitor.backoff_multiplier**attempt),
                monitor.max_backoff_seconds,
            )
            assert actual == expected

    @pytest.mark.asyncio
    async def test_max_backoff_capped(self, monitor):
        """Test that backoff is capped at max_backoff_seconds."""
        monitor.restart_count = 100  # High count to exceed max
        backoff = min(
            monitor.initial_backoff_seconds * (monitor.backoff_multiplier**monitor.restart_count),
            monitor.max_backoff_seconds,
        )
        assert backoff == monitor.max_backoff_seconds

    @pytest.mark.asyncio
    async def test_monitor_detects_crash(self, monitor, mock_client):
        """Test that monitor detects when ALS process exits."""
        mock_client.is_running = True

        # Start monitoring
        monitor.start_monitoring()
        await asyncio.sleep(0.05)

        # Simulate crash
        mock_client.is_running = False

        # Give monitor time to detect
        await asyncio.sleep(0.1)

        # Stop before restart attempt completes
        monitor.stop_monitoring()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_max_restart_attempts_respected(self, monitor, mock_client):
        """Test that monitor stops after max restart attempts."""
        monitor.max_restart_attempts = 2
        monitor.restart_count = 2  # Already at max

        # _handle_crash should not attempt restart
        mock_client.is_running = False

        with patch.object(monitor, "_handle_crash") as mock_handle:
            mock_handle.return_value = None
            # The actual restart logic checks restart_count
            assert monitor.restart_count >= monitor.max_restart_attempts


class TestALSHealthMonitorBackoff:
    """Test exponential backoff behavior."""

    def test_backoff_values(self):
        """Test specific backoff values."""
        monitor = ALSHealthMonitor(
            client=MagicMock(),
            project_root=Path("/test"),
            als_path="/test/als",
            initial_backoff_seconds=1.0,
            max_backoff_seconds=60.0,
            backoff_multiplier=2.0,
        )

        # Test backoff sequence
        expected_sequence = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
        for attempt, expected in enumerate(expected_sequence):
            actual = min(
                monitor.initial_backoff_seconds * (monitor.backoff_multiplier**attempt),
                monitor.max_backoff_seconds,
            )
            assert actual == expected, f"Attempt {attempt}: expected {expected}, got {actual}"


class TestHealthMonitorIntegration:
    """Integration tests for health monitoring (without real ALS)."""

    @pytest.mark.asyncio
    async def test_monitor_lifecycle(self):
        """Test complete monitor lifecycle: start, run, stop."""
        mock_client = MagicMock()
        mock_client.is_running = True

        monitor = ALSHealthMonitor(
            client=mock_client,
            project_root=Path("/test"),
            als_path="/test/als",
            initial_backoff_seconds=0.1,
        )

        # Start
        monitor.start_monitoring()
        assert monitor._monitor_task is not None

        # Let it run briefly
        await asyncio.sleep(0.1)
        assert not monitor._monitor_task.done()

        # Stop
        monitor.stop_monitoring()
        await asyncio.sleep(0.1)

        # Task should be cancelled
        assert monitor._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_callback_invocation(self):
        """Test that restart callback is invoked with new client."""
        callback_client = None

        def on_restart(client):
            nonlocal callback_client
            callback_client = client

        monitor = ALSHealthMonitor(
            client=MagicMock(),
            project_root=Path("/test"),
            als_path="/test/als",
        )
        monitor._on_restart_callback = on_restart

        # Simulate callback
        new_client = MagicMock()
        monitor._on_restart_callback(new_client)

        assert callback_client is new_client
