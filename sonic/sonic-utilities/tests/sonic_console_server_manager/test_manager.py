from __future__ import annotations

from copy import deepcopy

import pytest

import sonic_console_server_manager.manager as manager_module

from sonic_console_server_manager.manager import (
    GROUP_PORT_TABLE,
    GROUP_TABLE,
    PORT_TABLE,
    USER_GROUP_TABLE,
    USER_TABLE,
    ConfigDbConsolePortProvider,
    ConfigDbOperation,
    ConfigDbTransactionError,
    ConfigDbValidationError,
    DuplicatePortLabel,
    InvalidConsolePort,
    InvalidPortConfiguration,
    InvalidPortExpression,
    PasswordRequired,
    ConsoleServerManagerError,
    ReservedPortLabelConflict,
    SonicConfigDbBackend,
    SonicConsoleServerManager,
    SubprocessConsoleCliBackend,
    build_port_config,
    normalize_port_label,
    parse_port_expression,
    validate_ports,
    validate_reserved_port_label,
    validate_unique_label,
)


class FakeConfigDb:
    def __init__(self, tables=None, events=None):
        self.tables = deepcopy(tables or {})
        self.prevalidated = []
        self.committed = []
        self.direct_committed = []
        self.fail_commit = False
        self.events = events

    def get_table(self, table):
        return deepcopy(self.tables.get(table, {}))

    def get_entry(self, table, key):
        return deepcopy(self.tables.get(table, {}).get(key, {}))

    def prevalidate(self, operations):
        self.prevalidated.append(list(operations))
        if self.events is not None:
            self.events.append("prevalidate")

    def commit(self, operations):
        if self.events is not None:
            self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.committed.append(list(operations))
        self._apply_operations(operations)

    def commit_direct(self, operations):
        if self.events is not None:
            self.events.append("direct_commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.direct_committed.append(list(operations))
        self._apply_operations(operations)

    def _apply_operations(self, operations):
        for operation in operations:
            table = self.tables.setdefault(operation.table, {})
            matching_keys = [
                key
                for key in table
                if (
                    "|".join(map(str, key))
                    if isinstance(key, tuple)
                    else str(key)
                ) == operation.key
            ]
            if operation.action == "delete":
                table.pop(operation.key, None)
                for key in matching_keys:
                    table.pop(key, None)
            else:
                for key in matching_keys:
                    table.pop(key, None)
                table[operation.key] = dict(operation.fields or {})


class FakePortProvider:
    def __init__(self, ports):
        self.ports = set(ports)

    def get_valid_ports(self):
        return set(self.ports)


class FakeStatus:
    def __init__(self, events=None):
        self.calls = []
        self.fail = False
        self.events = events

    def run(self, arguments, *, quiet=True):
        self.calls.append(list(arguments))
        if self.events is not None:
            self.events.append("status")
        if self.fail:
            from sonic_console_server_manager.manager import CommandResult

            return CommandResult(1, "", "status failed")
        from sonic_console_server_manager.manager import CommandResult

        return CommandResult(0, "", "")


class FakeUsers_OBSOLETE:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.calls = []

    def exists(self, username):
        return username in self.existing

    def create(self, username, password):
        self.calls.append(("create", username, password))
        self.existing.add(username)

    def set_password(self, username, password):
        self.calls.append(("set_password", username, password))

    def delete(self, username):
        self.calls.append(("delete", username))
        self.existing.discard(username)


class FakeConsoleCli:
    def __init__(self, events=None):
        self.calls = []
        self.interactive_calls = []
        self.fail = False
        self.interactive_fail = False
        self.interactive_returncode = 0
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""
        self.events = events

    def run(self, arguments):
        self.calls.append(list(arguments))
        if self.events is not None:
            self.events.append("console_cli")
        from sonic_console_server_manager.manager import CommandResult
        if self.fail:
            return CommandResult(1, "", "console-cli failed")
        return CommandResult(self.returncode, self.stdout, self.stderr)

    def run_interactive(self, arguments):
        self.interactive_calls.append(list(arguments))
        if self.events is not None:
            self.events.append("console_cli_interactive")
        if self.interactive_fail:
            raise RuntimeError("interactive console-cli failed")
        return self.interactive_returncode


class FakeRawConfigDb:
    def __init__(self, tables=None):
        self.tables = deepcopy(tables or {})
        self.set_entry_calls = []
        self.fail_set_entry = False

    def get_table(self, table):
        return deepcopy(self.tables.get(table, {}))

    def get_entry(self, table, key):
        return deepcopy(self.tables.get(table, {}).get(key, {}))

    def set_entry(self, table, key, fields):
        self.set_entry_calls.append((table, key, deepcopy(fields)))
        if self.fail_set_entry:
            raise RuntimeError("set_entry failed")
        table_data = self.tables.setdefault(table, {})
        if fields is None:
            table_data.pop(key, None)
        else:
            table_data[key] = deepcopy(fields)


class FakeGenericUpdater:
    def __init__(self, calls, results=None):
        self.calls = calls
        self.results = list(results or [])

    def apply_patch(self, **kwargs):
        self.calls.append(kwargs)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return None


def make_sonic_config_db_backend(initial_config, *, updater_results=None):
    calls = []
    patches = []
    updater = FakeGenericUpdater(calls, updater_results)

    def config_loader(scope):
        assert scope == "host"
        return deepcopy(initial_config)

    def patch_builder(current, candidate):
        patch = {
            "current": deepcopy(current),
            "candidate": deepcopy(candidate),
        }
        patches.append(patch)
        return patch

    backend = SonicConfigDbBackend(
        scope="host",
        config_db=FakeRawConfigDb(initial_config),
        updater_factory=lambda: updater,
        config_loader=config_loader,
        patch_builder=patch_builder,
        config_format="CONFIGDB",
    )
    return backend, calls, patches



def test_create_default_manager_wires_production_backends(monkeypatch):
    created = {}

    class FakeProductionConfigDb:
        def __init__(self, *, scope=None):
            self.scope = scope
            created["config_db"] = self

    class FakeProductionPortProvider:
        def __init__(self, config_db):
            self.config_db = config_db
            created["port_provider"] = self

    class FakeProductionStatus:
        def __init__(self, command):
            self.command = command
            created["status"] = self

    class FakeProductionConsoleCli:
        def __init__(self, command):
            self.command = command
            created["console_cli"] = self

    monkeypatch.setattr(manager_module, "SonicConfigDbBackend", FakeProductionConfigDb)
    monkeypatch.setattr(manager_module, "ConfigDbConsolePortProvider", FakeProductionPortProvider)
    monkeypatch.setattr(manager_module, "SubprocessStatusBackend", FakeProductionStatus)
    monkeypatch.setattr(manager_module, "SubprocessConsoleCliBackend", FakeProductionConsoleCli)

    result = manager_module.create_default_manager(
        scope="host",
        status_command="/tmp/seriald-status",
        console_cli_command="/tmp/console-cli",
    )

    assert isinstance(result, SonicConsoleServerManager)
    assert created["config_db"].scope == "host"
    assert created["port_provider"].config_db is created["config_db"]
    assert created["status"].command == "/tmp/seriald-status"
    assert result._config_db is created["config_db"]
    assert result._port_provider is created["port_provider"]
    assert result._status is created["status"]
    assert result._console_cli is created["console_cli"]


def test_config_db_console_port_provider_uses_port_table_keys():
    provider = ConfigDbConsolePortProvider(
        FakeRawConfigDb(
            {
                PORT_TABLE: {
                    "1": {"label": "COM1"},
                    "3": {"label": "COM3"},
                    "8": {"label": "COM8"},
                }
            }
        )
    )

    assert provider.get_valid_ports() == {1, 3, 8}


def test_config_db_console_port_provider_rejects_missing_inventory():
    provider = ConfigDbConsolePortProvider(FakeRawConfigDb())

    with pytest.raises(InvalidConsolePort, match=PORT_TABLE):
        provider.get_valid_ports()


@pytest.mark.parametrize("key", ["tty1", "0", "-1"])
def test_config_db_console_port_provider_rejects_invalid_keys(key):
    provider = ConfigDbConsolePortProvider(
        FakeRawConfigDb({PORT_TABLE: {key: {}}})
    )

    with pytest.raises(InvalidConsolePort):
        provider.get_valid_ports()


def test_config_db_console_port_provider_rejects_duplicate_numeric_keys():
    provider = ConfigDbConsolePortProvider(
        FakeRawConfigDb({PORT_TABLE: {"1": {}, "01": {}}})
    )

    with pytest.raises(InvalidConsolePort, match="Duplicate console port 1"):
        provider.get_valid_ports()


def test_parse_port_expression():
    assert parse_port_expression("1-3,5,3") == [1, 2, 3, 5]
    assert parse_port_expression("all", all_ports={3, 1, 2}) == [1, 2, 3]


@pytest.mark.parametrize("value", ["", "1-", "1-a", "4-2", "1,,2"])
def test_parse_port_expression_rejects_invalid_syntax(value):
    with pytest.raises(InvalidPortExpression):
        parse_port_expression(value)


def test_validate_ports_uses_platform_set():
    validate_ports([1, 3], valid_ports={1, 3, 5})
    with pytest.raises(InvalidConsolePort):
        validate_ports([2], valid_ports={1, 3, 5})


def test_label_normalization_and_reserved_ownership():
    assert normalize_port_label(5, None) == "COM5"
    assert normalize_port_label(5, " com5 ") == "COM5"
    with pytest.raises(ReservedPortLabelConflict):
        validate_reserved_port_label(5, "com6", valid_ports={5, 6})


def test_custom_labels_are_case_sensitive_but_reserved_are_not():
    validate_unique_label(
        2,
        "router",
        existing_labels={1: "Router"},
        valid_ports={1, 2},
    )
    with pytest.raises(ReservedPortLabelConflict):
        validate_unique_label(
            2,
            "com1",
            existing_labels={1: "COM1"},
            valid_ports={1, 2},
        )


def test_build_port_config_materializes_complete_entry():
    candidate = build_port_config(
        1,
        {},
        {"baudrate": "115200"},
        valid_ports={1, 2},
        existing_labels={2: "COM2"},
    )
    assert candidate["baudrate"] == 115200
    assert candidate["label"] == "COM1"
    assert candidate["idle_timeout"] == 600


def test_set_port_config_uses_status_then_direct_commit():
    events = []
    db = FakeConfigDb(
        {PORT_TABLE: {"1": {"label": "COM1", "baudrate": 9600}}},
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_port_config(1, {"baudrate": 115200})

    assert events == ["status", "direct_commit"]
    assert not db.prevalidated
    assert db.direct_committed
    assert status.calls == [["config-port", "1", "--baudrate", "115200"]]
    assert db.tables[PORT_TABLE]["1"]["baudrate"] == 115200


def test_set_port_config_noop_skips_runtime_and_config_db_write():
    events = []
    db = FakeConfigDb(
        {PORT_TABLE: {"1": {"label": "COM1", "baudrate": "9600"}}},
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_port_config(1, {"baudrate": 9600})

    assert events == []
    assert status.calls == []
    assert not db.prevalidated
    assert not db.direct_committed
    assert db.tables[PORT_TABLE]["1"]["baudrate"] == "9600"


def test_set_port_config_sends_only_changed_runtime_fields():
    events = []
    db = FakeConfigDb(
        {
            PORT_TABLE: {
                "1": {
                    "label": "COM1",
                    "baudrate": "9600",
                    "parity": "none",
                }
            }
        },
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_port_config(
        1,
        {"baudrate": 9600, "parity": "even"},
    )

    assert events == ["status", "direct_commit"]
    assert status.calls == [["config-port", "1", "--parity", "even"]]
    assert db.tables[PORT_TABLE]["1"]["baudrate"] == 9600
    assert db.tables[PORT_TABLE]["1"]["parity"] == "even"


def test_set_port_config_rolls_back_runtime_on_commit_failure():
    events = []
    db = FakeConfigDb(
        {PORT_TABLE: {"1": {"label": "COM1", "baudrate": 9600}}},
        events=events,
    )
    db.fail_commit = True
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(ConfigDbTransactionError):
        manager.set_port_config(1, {"baudrate": 115200})

    assert events == ["status", "direct_commit", "status"]
    assert status.calls[0] == ["config-port", "1", "--baudrate", "115200"]
    assert status.calls[1][:2] == ["config-port", "1"]
    assert "9600" in status.calls[1]


def test_set_group_config_uses_one_status_call_and_direct_commit():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "console_user"}},
            GROUP_PORT_TABLE: {"ops|1": {}, "ops|2": {}},
        },
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2, 3}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_group_config(
        "ops",
        role="operator",
        ports="2-3",
    )

    assert events == ["status", "direct_commit"]
    assert not db.prevalidated
    assert not db.committed
    assert set(db.tables[GROUP_PORT_TABLE]) == {"ops|2", "ops|3"}
    assert db.tables[GROUP_TABLE]["ops"] == {"role": "operator"}
    assert status.calls == [[
        "config-group",
        "ops",
        "--role",
        "operator",
        "--ports",
        "2,3",
    ]]


def test_set_group_config_noop_skips_runtime_and_config_db():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "operator"}},
            GROUP_PORT_TABLE: {"ops|1": {}, "ops|2": {}},
        },
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_group_config(
        "ops",
        role="operator",
        ports="1-2",
    )

    assert events == []
    assert status.calls == []
    assert not db.direct_committed


def test_set_group_config_rolls_back_runtime_on_direct_commit_failure():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "console_user"}},
            GROUP_PORT_TABLE: {"ops|1": {}, "ops|2": {}},
        },
        events=events,
    )
    db.fail_commit = True
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2, 3}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(ConfigDbTransactionError):
        manager.set_group_config(
            "ops",
            role="operator",
            ports="2-3",
        )

    assert events == ["status", "direct_commit", "status"]
    assert status.calls[0] == [
        "config-group",
        "ops",
        "--role",
        "operator",
        "--ports",
        "2,3",
    ]
    assert status.calls[1] == [
        "config-group",
        "ops",
        "--role",
        "console_user",
        "--ports",
        "1,2",
    ]




def test_config_db_operation_contract():
    with pytest.raises(ValueError):
        ConfigDbOperation("set", "T", "K", None)
    with pytest.raises(ValueError):
        ConfigDbOperation("delete", "T", "K", {})


def test_sonic_config_db_backend_direct_commit_sets_complete_entry():
    raw_db = FakeRawConfigDb(
        {PORT_TABLE: {"1": {"label": "COM1", "baudrate": "9600"}}}
    )
    backend = SonicConfigDbBackend(
        scope="host",
        config_db=raw_db,
        updater_factory=lambda: None,
        config_loader=lambda scope: {},
        patch_builder=lambda current, candidate: None,
        config_format="CONFIGDB",
    )

    backend.commit_direct(
        [
            ConfigDbOperation(
                "set",
                PORT_TABLE,
                "1",
                {"label": "COM1", "baudrate": 115200},
            )
        ]
    )

    assert raw_db.set_entry_calls == [
        (
            PORT_TABLE,
            "1",
            {"label": "COM1", "baudrate": "115200"},
        )
    ]
    assert raw_db.tables[PORT_TABLE]["1"]["baudrate"] == "115200"


def test_sonic_config_db_backend_direct_commit_deletes_entry():
    raw_db = FakeRawConfigDb({GROUP_PORT_TABLE: {"ops|1": {}}})
    backend = SonicConfigDbBackend(
        scope="host",
        config_db=raw_db,
        updater_factory=lambda: None,
        config_loader=lambda scope: {},
        patch_builder=lambda current, candidate: None,
        config_format="CONFIGDB",
    )

    backend.commit_direct(
        [ConfigDbOperation("delete", GROUP_PORT_TABLE, "ops|1")]
    )

    assert raw_db.set_entry_calls == [(GROUP_PORT_TABLE, "ops|1", None)]
    assert "ops|1" not in raw_db.tables[GROUP_PORT_TABLE]


def test_sonic_config_db_backend_direct_commit_wraps_write_failure():
    raw_db = FakeRawConfigDb()
    raw_db.fail_set_entry = True
    backend = SonicConfigDbBackend(
        scope="host",
        config_db=raw_db,
        updater_factory=lambda: None,
        config_loader=lambda scope: {},
        patch_builder=lambda current, candidate: None,
        config_format="CONFIGDB",
    )

    with pytest.raises(ConfigDbTransactionError, match="set_entry failed"):
        backend.commit_direct(
            [ConfigDbOperation("set", PORT_TABLE, "1", {"baudrate": 9600})]
        )


def test_sonic_config_db_backend_prevalidates_then_commits_same_patch():
    backend, calls, patches = make_sonic_config_db_backend(
        {PORT_TABLE: {"1": {"label": "COM1", "baudrate": "9600"}}}
    )
    operations = [
        ConfigDbOperation(
            "set",
            PORT_TABLE,
            "1",
            {"label": "COM1", "baudrate": 115200},
        )
    ]

    backend.prevalidate(operations)
    backend.commit(operations)

    assert len(patches) == 1
    assert patches[0]["candidate"][PORT_TABLE]["1"] == {
        "label": "COM1",
        "baudrate": "115200",
    }
    assert [call["dry_run"] for call in calls] == [True, False]
    assert calls[0]["patch"] is calls[1]["patch"]
    assert all(call["config_format"] == "CONFIGDB" for call in calls)


def test_sonic_config_db_backend_builds_combined_set_delete_candidate():
    backend, calls, patches = make_sonic_config_db_backend(
        {
            GROUP_PORT_TABLE: {
                "ops|1": {},
                "ops|2": {},
            }
        }
    )
    operations = [
        ConfigDbOperation("delete", GROUP_PORT_TABLE, "ops|1"),
        ConfigDbOperation("set", GROUP_PORT_TABLE, "ops|3", {}),
    ]

    backend.prevalidate(operations)

    assert set(patches[0]["candidate"][GROUP_PORT_TABLE]) == {
        "ops|2",
        "ops|3",
    }
    assert calls[0]["dry_run"] is True


def test_sonic_config_db_backend_rejects_changed_operations_at_commit():
    backend, _, _ = make_sonic_config_db_backend({})
    validated = [ConfigDbOperation("set", "T", "K", {"f": "one"})]
    changed = [ConfigDbOperation("set", "T", "K", {"f": "two"})]

    backend.prevalidate(validated)

    with pytest.raises(ConfigDbTransactionError):
        backend.commit(changed)


def test_sonic_config_db_backend_wraps_dry_run_failure():
    backend, _, _ = make_sonic_config_db_backend(
        {},
        updater_results=[ValueError("CVL rejected candidate")],
    )
    operations = [ConfigDbOperation("set", "T", "K", {"f": "v"})]

    with pytest.raises(ConfigDbValidationError, match="CVL rejected candidate"):
        backend.prevalidate(operations)

    with pytest.raises(ConfigDbTransactionError):
        backend.commit(operations)


def test_set_group_config_accepts_tuple_keys_from_config_db():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "operator"}},
            GROUP_PORT_TABLE: {
                ("ops", "1"): {},
                ("ops", "2"): {},
                ("other", "3"): {},
            },
        },
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2, 3, 4}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.set_group_config(
        "ops",
        role="admin",
        ports="2-4",
    )

    assert events == ["status", "direct_commit"]
    assert set(db.tables[GROUP_PORT_TABLE]) == {
        ("other", "3"),
        "ops|2",
        "ops|3",
        "ops|4",
    }
    assert db.tables[GROUP_TABLE]["ops"] == {"role": "admin"}
    assert status.calls == [[
        "config-group",
        "ops",
        "--role",
        "admin",
        "--ports",
        "2,3,4",
    ]]



def test_delete_group_accepts_tuple_keys_from_config_db():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "operator"}},
            GROUP_PORT_TABLE: {
                ("ops", "1"): {},
                ("ops", "2"): {},
                ("other", "3"): {},
            },
            "CONSOLE_SERVER_USER_GROUP": {
                ("alice", "ops"): {},
                ("bob", "other"): {},
            },
        },
        events=events,
    )
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2, 3}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.delete_group("ops")

    assert events == ["status", "direct_commit"]
    assert not db.prevalidated
    assert not db.committed
    assert "ops" not in db.tables[GROUP_TABLE]
    assert set(db.tables[GROUP_PORT_TABLE]) == {("other", "3")}
    assert set(db.tables["CONSOLE_SERVER_USER_GROUP"]) == {("bob", "other")}
    assert status.calls == [["config-no-group", "ops"]]



def test_delete_group_noop_for_missing_group():
    events = []
    db = FakeConfigDb(events=events)
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.delete_group("missing")

    assert events == []
    assert status.calls == []
    assert not db.direct_committed


def test_delete_group_rolls_back_runtime_on_direct_commit_failure():
    events = []
    db = FakeConfigDb(
        {
            GROUP_TABLE: {"ops": {"role": "operator"}},
            GROUP_PORT_TABLE: {"ops|1": {}, "ops|2": {}},
        },
        events=events,
    )
    db.fail_commit = True
    status = FakeStatus(events=events)
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(ConfigDbTransactionError):
        manager.delete_group("ops")

    assert events == ["status", "direct_commit", "status"]
    assert status.calls == [
        ["config-no-group", "ops"],
        [
            "config-group",
            "ops",
            "--role",
            "operator",
            "--ports",
            "1,2",
        ],
    ]

def test_new_group_uses_yang_default_role():
    db = FakeConfigDb()
    status = FakeStatus()
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        console_cli_backend=FakeConsoleCli(),
    )

    manager.create_or_update_group("ops")

    assert db.tables[GROUP_TABLE]["ops"] == {"role": "console_user"}
    assert status.calls == [["config-group", "ops"]]



def test_user_config_calls_console_cli_and_directly_commits_metadata():
    events = []
    db = FakeConfigDb({GROUP_TABLE: {"ops": {"role": "operator"}}}, events=events)
    console_cli = FakeConsoleCli(events=events)
    manager = SonicConsoleServerManager(config_db=db, port_provider=FakePortProvider({1}), status_backend=FakeStatus(events=events), console_cli_backend=console_cli)

    manager.set_user_config("alice", "secret", "operator", ["ops"])

    assert events == ["console_cli", "direct_commit"]
    assert not db.prevalidated
    assert not db.committed
    assert db.tables["CONSOLE_SERVER_USER"]["alice"] == {"role": "operator"}
    assert "alice|ops" in db.tables["CONSOLE_SERVER_USER_GROUP"]
    assert console_cli.calls == [["config", "user", "add", "alice", "--password", "secret", "--role", "operator", "--groups", "ops"]]


def test_user_group_only_update_preserves_existing_role():
    db = FakeConfigDb(
        {
            USER_TABLE: {"alice": {"role": "admin"}},
            GROUP_TABLE: {"lab": {"role": "console_user"}},
            USER_GROUP_TABLE: {"alice|ops": {}},
        }
    )
    console_cli = FakeConsoleCli()
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    manager.set_user_config("alice", None, None, ["lab"])

    assert db.get_entry(USER_TABLE, "alice") == {"role": "admin"}
    assert not db.get_entry(USER_GROUP_TABLE, "alice|ops")
    assert db.get_entry(USER_GROUP_TABLE, "alice|lab") == {}
    assert console_cli.calls == [
        ["config", "user", "add", "alice", "--groups", "lab"]
    ]


def test_new_user_without_role_uses_none():
    db = FakeConfigDb()
    console_cli = FakeConsoleCli()
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    manager.set_user_config("alice", "secret", None, None)

    assert db.get_entry(USER_TABLE, "alice") == {"role": "none"}
    assert console_cli.calls == [
        ["config", "user", "add", "alice", "--password", "secret"]
    ]


def test_user_config_does_not_commit_when_console_cli_fails():
    events = []
    db = FakeConfigDb({GROUP_TABLE: {"ops": {"role": "operator"}}}, events=events)
    console_cli = FakeConsoleCli(events=events)
    console_cli.fail = True
    manager = SonicConsoleServerManager(config_db=db, port_provider=FakePortProvider({1}), status_backend=FakeStatus(), console_cli_backend=console_cli)

    with pytest.raises(Exception, match="console-cli failed"):
        manager.set_user_config("alice", "secret", "operator", ["ops"])

    assert events == ["console_cli"]
    assert not db.direct_committed
    assert not db.get_entry("CONSOLE_SERVER_USER", "alice")


def test_set_user_password_uses_console_cli_user_add():
    console_cli = FakeConsoleCli()
    manager = SonicConsoleServerManager(config_db=FakeConfigDb(), port_provider=FakePortProvider({1}), status_backend=FakeStatus(), console_cli_backend=console_cli)
    manager.set_user_password("alice", "secret")
    assert console_cli.calls == [["config", "user", "add", "alice", "--password", "secret"]]


def test_delete_user_uses_console_cli_and_direct_commit():
    events = []
    db = FakeConfigDb({"CONSOLE_SERVER_USER": {"alice": {"role": "operator"}}}, events=events)
    console_cli = FakeConsoleCli(events=events)
    manager = SonicConsoleServerManager(config_db=db, port_provider=FakePortProvider({1}), status_backend=FakeStatus(), console_cli_backend=console_cli)

    manager.delete_user("alice")

    assert events == ["console_cli", "direct_commit"]
    assert not db.prevalidated
    assert not db.committed
    assert not db.get_entry("CONSOLE_SERVER_USER", "alice")
    assert console_cli.calls == [["config", "user", "delete", "alice"]]


def test_delete_user_does_not_commit_when_console_cli_fails():
    events = []
    db = FakeConfigDb({"CONSOLE_SERVER_USER": {"alice": {"role": "operator"}}}, events=events)
    console_cli = FakeConsoleCli(events=events)
    console_cli.fail = True
    manager = SonicConsoleServerManager(config_db=db, port_provider=FakePortProvider({1}), status_backend=FakeStatus(), console_cli_backend=console_cli)

    with pytest.raises(Exception, match="console-cli failed"):
        manager.delete_user("alice")

    assert events == ["console_cli"]
    assert not db.direct_committed
    assert db.get_entry("CONSOLE_SERVER_USER", "alice") == {"role": "operator"}


def test_get_port_configs_returns_numeric_sorted_config_db_rows():
    db = FakeConfigDb(
        {
            PORT_TABLE: {
                "10": {"label": "COM10", "baudrate": "57600"},
                "2": {"label": "COM2", "baudrate": "115200"},
            }
        }
    )
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({2, 10}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    assert manager.get_port_configs() == [
        {"port": 2, "label": "COM2", "baudrate": "115200"},
        {"port": 10, "label": "COM10", "baudrate": "57600"},
    ]


def test_get_user_configs_aggregates_tuple_and_string_group_keys():
    db = FakeConfigDb(
        {
            "CONSOLE_SERVER_USER": {
                "bob": {"role": "none"},
                "alice": {"role": "operator"},
            },
            "CONSOLE_SERVER_USER_GROUP": {
                ("alice", "ops"): {},
                "alice|lab": {},
            },
        }
    )
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    assert manager.get_user_configs() == [
        {"username": "alice", "role": "operator", "groups": ["lab", "ops"]},
        {"username": "bob", "role": "none", "groups": []},
    ]


def test_get_group_configs_aggregates_and_sorts_ports_numerically():
    db = FakeConfigDb(
        {
            GROUP_TABLE: {
                "ops": {"role": "operator"},
                "lab": {"role": "console_user"},
            },
            GROUP_PORT_TABLE: {
                ("ops", "10"): {},
                "ops|2": {},
                "lab|1": {},
            },
        }
    )
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1, 2, 10}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    assert manager.get_group_configs() == [
        {"group": "lab", "role": "console_user", "ports": [1]},
        {"group": "ops", "role": "operator", "ports": [2, 10]},
    ]


def test_resolve_port_by_label_returns_matching_port():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(
            {
                PORT_TABLE: {
                    "1": {"label": "COM1"},
                    "5": {"label": "BackupConsole"},
                    "8": {"label": "Router Console"},
                }
            }
        ),
        port_provider=FakePortProvider({1, 5, 8}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    assert manager.resolve_port_by_label("BackupConsole") == 5


def test_resolve_port_by_label_is_case_sensitive():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(
            {PORT_TABLE: {"5": {"label": "BackupConsole"}}}
        ),
        port_provider=FakePortProvider({5}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(
        InvalidConsolePort,
        match="No console port has label 'backupconsole'",
    ):
        manager.resolve_port_by_label("backupconsole")


def test_resolve_port_by_label_rejects_unknown_label():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(
            {PORT_TABLE: {"1": {"label": "COM1"}}}
        ),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(
        InvalidConsolePort,
        match="No console port has label 'Missing'",
    ):
        manager.resolve_port_by_label("Missing")


def test_resolve_port_by_label_detects_duplicate_config_db_data():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(
            {
                PORT_TABLE: {
                    "1": {"label": "Duplicate"},
                    "2": {"label": "Duplicate"},
                }
            }
        ),
        port_provider=FakePortProvider({1, 2}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(
        DuplicatePortLabel,
        match=(
            "Label 'Duplicate' is assigned to multiple "
            "console ports: 1, 2"
        ),
    ):
        manager.resolve_port_by_label("Duplicate")


def test_resolve_port_by_label_rejects_empty_label():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(
            {PORT_TABLE: {"1": {"label": "COM1"}}}
        ),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=FakeConsoleCli(),
    )

    with pytest.raises(
        InvalidPortConfiguration,
        match="Console port label must not be empty",
    ):
        manager.resolve_port_by_label("   ")


def test_connect_line_validates_port_and_runs_interactive_console_cli():
    console_cli = FakeConsoleCli()
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1, 5, 8}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    assert manager.connect_line(5) == 0
    assert console_cli.interactive_calls == [["connect", "5"]]
    assert console_cli.calls == []


def test_connect_line_rejects_unknown_port_before_execution():
    console_cli = FakeConsoleCli()
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1, 5, 8}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    with pytest.raises(
        InvalidConsolePort,
        match="Invalid console port",
    ):
        manager.connect_line(99)

    assert console_cli.interactive_calls == []


def test_connect_line_returns_console_cli_exit_status():
    console_cli = FakeConsoleCli()
    console_cli.interactive_returncode = 9
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1, 5, 8}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    assert manager.connect_line(5) == 9
    assert console_cli.interactive_calls == [["connect", "5"]]


def test_connect_line_wraps_unexpected_backend_failure():
    console_cli = FakeConsoleCli()
    console_cli.interactive_fail = True
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({5}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    with pytest.raises(
        ConsoleServerManagerError,
        match="Failed to connect to console port 5",
    ):
        manager.connect_line(5)


def test_console_cli_run_interactive_inherits_terminal(
    monkeypatch,
    tmp_path,
):
    command = tmp_path / "console-cli"
    command.write_text("#!/bin/sh\\n")
    command.chmod(0o755)
    calls = []

    class Completed:
        returncode = 4

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return Completed()

    monkeypatch.setattr(manager_module.subprocess, "run", fake_run)

    backend = SubprocessConsoleCliBackend(str(command))

    assert backend.run_interactive(["connect", "5"]) == 4
    assert calls == [
        (
            [str(command), "connect", "5"],
            {"check": False},
        )
    ]

def test_get_sessions_calls_console_cli_and_flattens_active_clients():
    console_cli = FakeConsoleCli()
    console_cli.stdout = """
{
  "op": "status",
  "lines": [
    {
      "line": 1,
      "mode": "shared",
      "clients": [
        {
          "session_id": "hidden-session-id",
          "user": "admin",
          "role": "writer",
          "ip": "10.19.252.103",
          "port": 36736,
          "idle_timeout": 600,
          "last_activity": 1783509387.8,
          "time_left": 479
        },
        {
          "session_id": "another-hidden-id",
          "user": "admin",
          "role": "writer",
          "ip": "127.0.0.1",
          "port": 38454,
          "idle_timeout": 600,
          "last_activity": 1783509057.3,
          "time_left": 149
        }
      ]
    },
    {
      "line": 2,
      "mode": "shared",
      "clients": []
    }
  ]
}
"""
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1, 2}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    assert manager.get_sessions() == [
        {
            "line": 1,
            "mode": "shared",
            "user": "admin",
            "role": "writer",
            "ip": "10.19.252.103",
            "port": 36736,
            "idle_timeout": 600,
            "time_left": 479,
        },
        {
            "line": 1,
            "mode": "shared",
            "user": "admin",
            "role": "writer",
            "ip": "127.0.0.1",
            "port": 38454,
            "idle_timeout": 600,
            "time_left": 149,
        },
    ]
    assert console_cli.calls == [["show", "sessions", "--json"]]


def test_get_sessions_returns_empty_list_when_no_clients_are_active():
    console_cli = FakeConsoleCli()
    console_cli.stdout = '{"op":"status","lines":[{"line":1,"mode":"shared","clients":[]}]}'
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    assert manager.get_sessions() == []


def test_get_sessions_rejects_invalid_json():
    console_cli = FakeConsoleCli()
    console_cli.stdout = "not-json"
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    with pytest.raises(
        manager_module.ConsoleServerCommandError,
        match="invalid session JSON",
    ):
        manager.get_sessions()


def test_get_sessions_rejects_missing_lines_list():
    console_cli = FakeConsoleCli()
    console_cli.stdout = '{"op":"status"}'
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        console_cli_backend=console_cli,
    )

    with pytest.raises(
        manager_module.ConsoleServerCommandError,
        match="lines list",
    ):
        manager.get_sessions()

