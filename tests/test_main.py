"""Tests for the Ada MCP process entry point."""

import logging

import pytest

from ada_mcp.__main__ import main


def test_main_rejects_invalid_scenario_variables(monkeypatch, caplog):
    """Invalid process configuration fails before the first MCP request."""
    monkeypatch.setenv("ADA_PROJECT_SCENARIO_VARIABLES", "not-json")
    caplog.set_level(logging.ERROR)

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 1
    assert "must be a JSON object of string values" in caplog.text
