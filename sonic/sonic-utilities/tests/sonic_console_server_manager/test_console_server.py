from __future__ import annotations

from click.testing import CliRunner
import pytest

import config.console_server as console_server_module
from config.console_server import console_server
from sonic_console_server_manager.manager import InvalidConsolePort


class FakeManager:
    def __init__(self):
        self.calls = []
        self.error = None

    def set_port_config(self, port_number, updates):
        self.calls.append((port_number, updates))
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["port", "baudrate", "1", "115200"], (1, {"baudrate": 115200})),
        (["port", "databits", "2", "8"], (2, {"databits": 8})),
        (["port", "parity", "3", "even"], (3, {"parity": "even"})),
        (["port", "stopbits", "4", "2"], (4, {"stopbits": 2})),
        (["port", "flowcontrol", "5", "rtscts"], (5, {"flowcontrol": "rtscts"})),
        (["port", "mode", "6", "shared"], (6, {"mode": "shared"})),
    ],
)
def test_port_commands_call_shared_manager(monkeypatch, arguments, expected):
    manager = FakeManager()
    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        lambda: manager,
    )

    result = CliRunner().invoke(console_server, arguments)

    assert result.exit_code == 0, result.output
    assert manager.calls == [expected]


def test_manager_error_is_reported_as_click_error(monkeypatch):
    manager = FakeManager()
    manager.error = InvalidConsolePort("Invalid console port(s): 99")
    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        lambda: manager,
    )

    result = CliRunner().invoke(
        console_server,
        ["port", "baudrate", "99", "115200"],
    )

    assert result.exit_code != 0
    assert "Invalid console port(s): 99" in result.output


def test_click_rejects_non_integer_port_before_manager_creation(monkeypatch):
    created = []

    def create_manager():
        created.append(True)
        return FakeManager()

    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        create_manager,
    )

    result = CliRunner().invoke(
        console_server,
        ["port", "baudrate", "not-a-port", "115200"],
    )

    assert result.exit_code != 0
    assert created == []
