from __future__ import annotations

from copy import deepcopy

import pytest

import sonic_console_server_manager.manager as manager_module

from sonic_console_server_manager.manager import (
    GROUP_PORT_TABLE,
    GROUP_TABLE,
    PORT_TABLE,
    ConfigDbConsolePortProvider,
    ConfigDbOperation,
    ConfigDbTransactionError,
    ConfigDbValidationError,
    DuplicatePortLabel,
    InvalidConsolePort,
    InvalidPortExpression,
    PasswordRequired,
    ReservedPortLabelConflict,
    SonicConfigDbBackend,
    SonicConsoleServerManager,
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
        for operation in operations:
            table = self.tables.setdefault(operation.table, {})
            if operation.action == "delete":
                table.pop(operation.key, None)
            else:
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


class FakeUsers:
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


class FakeRawConfigDb:
    def __init__(self, tables=None):
        self.tables = deepcopy(tables or {})

    def get_table(self, table):
        return deepcopy(self.tables.get(table, {}))

    def get_entry(self, table, key):
        return deepcopy(self.tables.get(table, {}).get(key, {}))


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

    class FakeProductionUsers:
        def __init__(self):
            created["users"] = self

    monkeypatch.setattr(manager_module, "SonicConfigDbBackend", FakeProductionConfigDb)
    monkeypatch.setattr(manager_module, "ConfigDbConsolePortProvider", FakeProductionPortProvider)
    monkeypatch.setattr(manager_module, "SubprocessStatusBackend", FakeProductionStatus)
    monkeypatch.setattr(manager_module, "NssUserBackend", FakeProductionUsers)

    result = manager_module.create_default_manager(
        scope="host",
        status_command="/tmp/seriald-status",
    )

    assert isinstance(result, SonicConsoleServerManager)
    assert created["config_db"].scope == "host"
    assert created["port_provider"].config_db is created["config_db"]
    assert created["status"].command == "/tmp/seriald-status"
    assert result._config_db is created["config_db"]
    assert result._port_provider is created["port_provider"]
    assert result._status is created["status"]
    assert result._users is created["users"]


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
    assert candidate["idle_timeout"] == 0


def test_set_port_config_prevalidates_calls_status_then_commits():
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
        user_backend=FakeUsers(),
    )

    manager.set_port_config(1, {"baudrate": 115200})

    assert events == ["prevalidate", "status", "commit"]
    assert db.prevalidated
    assert status.calls == [["config-port", "1", "--baudrate", "115200"]]
    assert db.tables[PORT_TABLE]["1"]["baudrate"] == 115200


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
        user_backend=FakeUsers(),
    )

    with pytest.raises(ConfigDbTransactionError):
        manager.set_port_config(1, {"baudrate": 115200})

    assert events == ["prevalidate", "status", "commit", "status"]
    assert status.calls[0] == ["config-port", "1", "--baudrate", "115200"]
    assert status.calls[1][:2] == ["config-port", "1"]
    assert "9600" in status.calls[1]


def test_set_group_ports_replaces_mapping():
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
        port_provider=FakePortProvider({1, 2, 3}),
        status_backend=status,
        user_backend=FakeUsers(),
    )

    manager.set_group_ports("ops", "2-3")

    assert events == ["prevalidate", "status", "commit"]
    assert set(db.tables[GROUP_PORT_TABLE]) == {"ops|2", "ops|3"}
    assert status.calls == [["config-group", "ops", "--ports", "2,3"]]


def test_new_user_requires_password():
    manager = SonicConsoleServerManager(
        config_db=FakeConfigDb(),
        port_provider=FakePortProvider({1}),
        status_backend=FakeStatus(),
        user_backend=FakeUsers(),
    )
    with pytest.raises(PasswordRequired):
        manager.set_user_config("alice", None, "operator", None)


def test_existing_user_without_metadata_is_imported_without_password_change():
    db = FakeConfigDb()
    users = FakeUsers(existing={"alice"})
    status = FakeStatus()
    manager = SonicConsoleServerManager(
        config_db=db,
        port_provider=FakePortProvider({1}),
        status_backend=status,
        user_backend=users,
    )

    manager.set_user_config("alice", None, "operator", None)
    assert db.tables["CONSOLE_SERVER_USER"]["alice"] == {"role": "operator"}
    assert not [call for call in users.calls if call[0] == "set_password"]


def test_config_db_operation_contract():
    with pytest.raises(ValueError):
        ConfigDbOperation("set", "T", "K", None)
    with pytest.raises(ValueError):
        ConfigDbOperation("delete", "T", "K", {})


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
