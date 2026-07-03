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

    def _record(self, call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def set_port_config(self, port_number, updates):
        self._record(("set_port_config", port_number, updates))

    def create_or_update_group(self, group_name, *, role=None):
        self._record(("create_or_update_group", group_name, role))

    def set_group_ports(self, group_name, ports):
        self._record(("set_group_ports", group_name, ports))

    def delete_group(self, group_name):
        self._record(("delete_group", group_name))


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["port", "baudrate", "1", "115200"], (1, {"baudrate": 115200})),
        (["port", "databits", "2", "8"], (2, {"databits": 8})),
        (["port", "parity", "3", "even"], (3, {"parity": "even"})),
        (["port", "stopbits", "4", "2"], (4, {"stopbits": 2})),
        (["port", "flowcontrol", "5", "rtscts"], (5, {"flowcontrol": "rtscts"})),
        (["port", "mode", "6", "shared"], (6, {"mode": "shared"})),
        (["port", "max-clients", "7", "4"], (7, {"max_clients": 4})),
        (["port", "idle-timeout", "8", "600"], (8, {"idle_timeout": 600})),
        (["port", "label", "9", "RouterA"], (9, {"label": "RouterA"})),
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
    assert manager.calls == [("set_port_config", expected[0], expected[1])]


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

@pytest.mark.parametrize(
    ("arguments", "expected_calls"),
    [
        (
            ["group", "add", "ops", "1-4,8"],
            [
                ("create_or_update_group", "ops", "console_user"),
                ("set_group_ports", "ops", "1-4,8"),
            ],
        ),
        (
            ["group", "add", "ops", "1,3-4", "--role", "operator"],
            [
                ("create_or_update_group", "ops", "operator"),
                ("set_group_ports", "ops", "1,3-4"),
            ],
        ),
        (
            ["group", "add", "ops", "all", "--role", "admin"],
            [
                ("create_or_update_group", "ops", "admin"),
                ("set_group_ports", "ops", "all"),
            ],
        ),
        (
            ["group", "delete", "ops"],
            [("delete_group", "ops")],
        ),
    ],
)
def test_group_commands_call_shared_manager(
    monkeypatch,
    arguments,
    expected_calls,
):
    manager = FakeManager()
    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        lambda: manager,
    )

    result = CliRunner().invoke(console_server, arguments)

    assert result.exit_code == 0, result.output
    assert manager.calls == expected_calls


def test_group_add_help_shows_yang_default_role():
    result = CliRunner().invoke(console_server, ["group", "add", "--help"])

    assert result.exit_code == 0, result.output
    assert "console_user" in result.output
    assert "default" in result.output.lower()


def test_group_manager_error_is_reported_as_click_error(monkeypatch):
    manager = FakeManager()
    manager.error = InvalidConsolePort("Invalid console port(s): 99")
    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        lambda: manager,
    )

    result = CliRunner().invoke(
        console_server,
        ["group", "add", "ops", "99"],
    )

    assert result.exit_code != 0
    assert "Invalid console port(s): 99" in result.output


def test_click_rejects_missing_group_port_list_before_manager_creation(monkeypatch):
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
        ["group", "add", "ops"],
    )

    assert result.exit_code != 0
    assert "Missing argument 'PORT_LIST'" in result.output
    assert created == []


def test_click_rejects_invalid_group_role_before_manager_creation(monkeypatch):
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
        ["group", "add", "ops", "1", "--role", "observer"],
    )

    assert result.exit_code != 0
    assert created == []

