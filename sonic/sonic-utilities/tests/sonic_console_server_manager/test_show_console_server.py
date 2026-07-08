from __future__ import annotations

from click.testing import CliRunner

import show.console_server as show_console_server_module
from show.console_server import console_server
from sonic_console_server_manager.manager import ConsoleServerManagerError


class FakeManager:
    def __init__(self):
        self.ports = []
        self.users = []
        self.groups = []
        self.error = None

    def _return(self, value):
        if self.error is not None:
            raise self.error
        return value

    def get_port_configs(self):
        return self._return(self.ports)

    def get_user_configs(self):
        return self._return(self.users)

    def get_group_configs(self):
        return self._return(self.groups)


def _install_manager(monkeypatch, manager):
    monkeypatch.setattr(
        show_console_server_module,
        "create_default_manager",
        lambda: manager,
    )


def test_show_port_formats_config_db_fields(monkeypatch):
    manager = FakeManager()
    manager.ports = [
        {
            "port": 1,
            "label": "COM1",
            "mode": "shared",
            "max_clients": "4",
            "idle_timeout": "600",
            "baudrate": "115200",
            "databits": "8",
            "stopbits": "1",
            "parity": "none",
            "flowcontrol": "none",
        }
    ]
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["port"])

    assert result.exit_code == 0, result.output
    assert "Line" in result.output
    assert "Flowcontrol" in result.output
    assert "COM1" in result.output
    assert "115200" in result.output
    assert "tcp_port" not in result.output
    assert "interface" not in result.output.lower()


def test_show_user_formats_role_and_groups(monkeypatch):
    manager = FakeManager()
    manager.users = [
        {"username": "alice", "role": "operator", "groups": ["lab", "ops"]},
        {"username": "bob", "role": "none", "groups": []},
    ]
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["user"])

    assert result.exit_code == 0, result.output
    assert "Username" in result.output
    assert "alice" in result.output
    assert "lab,ops" in result.output
    assert "bob" in result.output


def test_show_group_formats_role_and_ports(monkeypatch):
    manager = FakeManager()
    manager.groups = [
        {"group": "ops", "role": "operator", "ports": [1, 2, 10]},
    ]
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["group"])

    assert result.exit_code == 0, result.output
    assert "Group" in result.output
    assert "ops" in result.output
    assert "1,2,10" in result.output


def test_show_commands_report_empty_tables(monkeypatch):
    manager = FakeManager()
    _install_manager(monkeypatch, manager)

    runner = CliRunner()
    for command, expected in [
        ("port", "No console-server ports configured."),
        ("user", "No console-server users configured."),
        ("group", "No console-server groups configured."),
    ]:
        result = runner.invoke(console_server, [command])
        assert result.exit_code == 0, result.output
        assert expected in result.output


def test_show_manager_error_is_reported_as_click_error(monkeypatch):
    manager = FakeManager()
    manager.error = ConsoleServerManagerError("ConfigDB unavailable")
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["port"])

    assert result.exit_code != 0
    assert "ConfigDB unavailable" in result.output
