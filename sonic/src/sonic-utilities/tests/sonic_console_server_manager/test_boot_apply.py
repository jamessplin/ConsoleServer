import json
import logging

import pytest

from sonic_console_server_manager.boot_apply import BootApplyError, ConsoleServerBootApply
from sonic_console_server_manager.manager import CommandResult


class FakeConfigDb:
    def __init__(self, tables):
        self.tables = tables

    def get_table(self, table):
        return self.tables.get(table, {})

    def get_entry(self, table, key):
        return self.tables.get(table, {}).get(key, {})


class FakeStatus:
    def __init__(self, runtime_groups=None, runtime_users=None):
        self.runtime_groups = runtime_groups or {}
        self.runtime_users = runtime_users or {}
        self.calls = []

    def run(self, arguments, *, quiet=True):
        args = list(arguments)
        self.calls.append(args)
        if args == ["show-running-config", "--groups"]:
            return CommandResult(0, json.dumps({"groups": self.runtime_groups}))
        if args == ["show-running-config", "--users"]:
            return CommandResult(0, json.dumps({"users": self.runtime_users}))
        return CommandResult(0)


class FakeConsoleCli:
    def __init__(self):
        self.calls = []

    def run(self, arguments):
        self.calls.append(list(arguments))
        return CommandResult(0)


def base_tables():
    return {
        "CONSOLE_SERVER_PORT": {
            "1": {
                "baudrate": "9600",
                "databits": "8",
                "parity": "none",
                "stopbits": "1",
                "flowcontrol": "xonxoff",
                "mode": "shared",
                "max_clients": "1",
                "idle_timeout": "600",
                "label": "COM1",
            }
        },
        "CONSOLE_SERVER_GROUP": {
            "operators": {"role": "operator"},
        },
        "CONSOLE_SERVER_GROUP_PORT": {
            ("operators", "1"): {},
        },
        "CONSOLE_SERVER_USER": {
            "admin": {"role": "admin"},
            "missing": {"role": "none"},
        },
        "CONSOLE_SERVER_USER_GROUP": {
            ("admin", "operators"): {},
        },
        "CONSOLE_SERVER_PRODUCT_INFO": {
            "global": {
                "base_port": "35000",
                "max_ports": "1",
                "max_users": "16",
                "max_groups": "16",
            }
        },
    }


def test_boot_apply_replays_ports_replaces_groups_and_updates_existing_users(caplog):
    status = FakeStatus(
        runtime_groups={"old-bootstrap-group": {}, "operators": {}},
        runtime_users={"legacy": {}, "admin": {}},
    )
    cli = FakeConsoleCli()
    apply = ConsoleServerBootApply(
        config_db=FakeConfigDb(base_tables()),
        status_backend=status,
        console_cli_backend=cli,
        local_user_exists=lambda username: username == "admin",
    )

    with caplog.at_level(logging.WARNING):
        summary = apply.apply()

    assert summary.ports == 1
    assert summary.groups == 1
    assert summary.users == 1
    assert summary.unmanaged_users == 2
    assert ["config-no-group", "old-bootstrap-group"] in status.calls
    assert [
        "config-group", "operators", "--role", "operator", "--ports", "1"
    ] in status.calls
    assert any(call[:2] == ["config-port", "1"] and "xonxoff" in call for call in status.calls)
    assert cli.calls == [[
        "config", "user", "add", "admin", "--role", "admin",
        "--groups", "operators",
    ]]
    assert all("password" not in " ".join(call).lower() for call in cli.calls)
    assert "Preserving unmanaged ConfigDB user missing" in caplog.text
    assert "Preserving unmanaged runtime user legacy" in caplog.text


def test_product_info_is_validation_only():
    status = FakeStatus()
    cli = FakeConsoleCli()
    apply = ConsoleServerBootApply(
        config_db=FakeConfigDb(base_tables()),
        status_backend=status,
        console_cli_backend=cli,
        local_user_exists=lambda username: False,
    )

    apply.apply()

    assert not any("product" in " ".join(call) for call in status.calls)
    assert not any("product" in " ".join(call) for call in cli.calls)


def test_invalid_snapshot_fails_before_runtime_changes():
    tables = base_tables()
    tables["CONSOLE_SERVER_PORT"]["1"]["flowcontrol"] = "hardware"
    status = FakeStatus()
    cli = FakeConsoleCli()
    apply = ConsoleServerBootApply(
        config_db=FakeConfigDb(tables),
        status_backend=status,
        console_cli_backend=cli,
        local_user_exists=lambda username: True,
    )

    with pytest.raises(BootApplyError, match="flowcontrol"):
        apply.apply()

    assert status.calls == []
    assert cli.calls == []


def test_missing_product_info_fails_validation():
    tables = base_tables()
    tables["CONSOLE_SERVER_PRODUCT_INFO"] = {}
    apply = ConsoleServerBootApply(
        config_db=FakeConfigDb(tables),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(BootApplyError, match="CONSOLE_SERVER_PRODUCT_INFO"):
        apply.apply()
