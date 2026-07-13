from __future__ import annotations

from click.testing import CliRunner

import connect.console_server as console_server_module
from connect.console_server import console_server
from sonic_console_server_manager.manager import InvalidConsolePort


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.labels = {
            "BackupConsole": 5,
            "Backup Console": 8,
        }
        self.connect_exit_status = 0
        self.connect_error: Exception | None = None

    def resolve_port_by_label(self, label: str) -> int:
        self.calls.append(("resolve_port_by_label", label))
        if label not in self.labels:
            raise InvalidConsolePort(
                f"No console port has label '{label}'"
            )
        return self.labels[label]

    def connect_line(self, port_number: int) -> int:
        self.calls.append(("connect_line", port_number))
        if self.connect_error is not None:
            raise self.connect_error
        return self.connect_exit_status


def _install_manager(monkeypatch, manager: FakeManager) -> None:
    monkeypatch.setattr(
        console_server_module,
        "create_default_manager",
        lambda: manager,
    )


def test_connect_line_calls_manager(monkeypatch):
    manager = FakeManager()
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["line", "5"])

    assert result.exit_code == 0
    assert manager.calls == [("connect_line", 5)]


def test_connect_line_rejects_non_integer():
    result = CliRunner().invoke(
        console_server,
        ["line", "not-a-number"],
    )

    assert result.exit_code == 2
    assert "not a valid integer" in result.output


def test_connect_line_reports_manager_error(monkeypatch):
    manager = FakeManager()
    manager.connect_error = InvalidConsolePort(
        "Invalid console port(s): 99"
    )
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["line", "99"])

    assert result.exit_code == 1
    assert "Invalid console port(s): 99" in result.output


def test_connect_line_propagates_nonzero_exit_status(monkeypatch):
    manager = FakeManager()
    manager.connect_exit_status = 7
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(console_server, ["line", "5"])

    assert result.exit_code == 7
    assert manager.calls == [("connect_line", 5)]


def test_connect_label_resolves_and_connects(monkeypatch):
    manager = FakeManager()
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(
        console_server,
        ["label", "BackupConsole"],
    )

    assert result.exit_code == 0
    assert manager.calls == [
        ("resolve_port_by_label", "BackupConsole"),
        ("connect_line", 5),
    ]


def test_connect_label_reports_unknown_label(monkeypatch):
    manager = FakeManager()
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(
        console_server,
        ["label", "UnknownConsole"],
    )

    assert result.exit_code == 1
    assert (
        "No console port has label 'UnknownConsole'"
        in result.output
    )
    assert manager.calls == [
        ("resolve_port_by_label", "UnknownConsole"),
    ]


def test_connect_label_preserves_spaces(monkeypatch):
    manager = FakeManager()
    _install_manager(monkeypatch, manager)

    result = CliRunner().invoke(
        console_server,
        ["label", "Backup Console"],
    )

    assert result.exit_code == 0
    assert manager.calls == [
        ("resolve_port_by_label", "Backup Console"),
        ("connect_line", 8),
    ]
