"""Shared SONiC manager for the generic ConsoleServer component.

The generic ConsoleServer implementation is intentionally SONiC-agnostic.
This module provides the SONiC integration layer used by config/show/REST:

1. normalize and validate input;
2. use feature-specific validation for interactive port updates;
3. call the generic ``seriald-status`` command;
4. commit interactive port and group updates directly to ConfigDB;
5. retain GCU/CVL for user metadata transactions during migration;
6. perform compensating runtime rollback when the final commit fails.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Protocol, Sequence


PORT_TABLE = "CONSOLE_SERVER_PORT"
GROUP_TABLE = "CONSOLE_SERVER_GROUP"
GROUP_PORT_TABLE = "CONSOLE_SERVER_GROUP_PORT"
USER_TABLE = "CONSOLE_SERVER_USER"
USER_GROUP_TABLE = "CONSOLE_SERVER_USER_GROUP"

PORT_FIELDS = {
    "baudrate",
    "databits",
    "parity",
    "stopbits",
    "flowcontrol",
    "mode",
    "max_clients",
    "idle_timeout",
    "label",
}

PORT_DEFAULTS: dict[str, Any] = {
    "baudrate": 115200,
    "databits": 8,
    "parity": "none",
    "stopbits": 1,
    "flowcontrol": "none",
    "mode": "shared",
    "max_clients": 1,
    "idle_timeout": 600,
}

ALLOWED_BAUDRATES = {
    300,
    1200,
    2400,
    4800,
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
    921600,
}
ALLOWED_DATABITS = {5, 6, 7, 8}
ALLOWED_PARITY = {"none", "even", "odd", "mark", "space"}
ALLOWED_STOPBITS = {1, 2}
ALLOWED_FLOWCONTROL = {"none", "rtscts", "xonxoff"}
ALLOWED_MODES = {"exclusive", "shared"}
ALLOWED_GROUP_ROLES = {"admin", "console_user", "operator"}
ALLOWED_USER_ROLES = {"admin", "console_user", "operator", "none"}

_RESERVED_LABEL_RE = re.compile(r"^COM([1-9][0-9]*)$", re.IGNORECASE)
_USERNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConsoleServerManagerError(Exception):
    """Base error for the SONiC ConsoleServer integration layer."""


class InvalidPortExpression(ConsoleServerManagerError):
    pass


class InvalidConsolePort(ConsoleServerManagerError):
    pass


class DuplicateConsolePort(ConsoleServerManagerError):
    pass


class InvalidPortConfiguration(ConsoleServerManagerError):
    pass


class ReservedPortLabelConflict(ConsoleServerManagerError):
    pass


class DuplicatePortLabel(ConsoleServerManagerError):
    pass


class MissingStoredPortLabel(ConsoleServerManagerError):
    pass


class LocalUserNotFound(ConsoleServerManagerError):
    pass


class PasswordRequired(ConsoleServerManagerError):
    code = "CONSOLE_SERVER_PASSWORD_REQUIRED"


class ConsoleServerCommandError(ConsoleServerManagerError):
    pass


class ConfigDbValidationError(ConsoleServerManagerError):
    pass


class ConfigDbTransactionError(ConsoleServerManagerError):
    pass


class RuntimeRollbackError(ConsoleServerManagerError):
    """The ConfigDB operation failed and runtime rollback also failed."""

    def __init__(self, original_error: Exception, rollback_error: Exception):
        super().__init__(
            f"ConfigDB commit failed ({original_error}); runtime rollback also "
            f"failed ({rollback_error})"
        )
        self.original_error = original_error
        self.rollback_error = rollback_error


# ---------------------------------------------------------------------------
# Data types and backend protocols
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigDbOperation:
    action: Literal["set", "delete"]
    table: str
    key: str
    fields: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.action == "set" and self.fields is None:
            raise ValueError("A set operation requires fields")
        if self.action == "delete" and self.fields is not None:
            raise ValueError("A delete operation must not contain fields")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ConfigDbBackend(Protocol):
    def get_table(self, table: str) -> Mapping[str, Mapping[str, Any]]:
        ...

    def get_entry(self, table: str, key: str) -> Mapping[str, Any]:
        ...

    def prevalidate(self, operations: Sequence[ConfigDbOperation]) -> None:
        """Validate the complete candidate state through YANG/CVL."""

    def commit(self, operations: Sequence[ConfigDbOperation]) -> None:
        """Commit prevalidated ConfigDB operations through GCU."""

    def commit_direct(self, operations: Sequence[ConfigDbOperation]) -> None:
        """Commit feature-validated operations directly to ConfigDB."""


class PortProvider(Protocol):
    def get_valid_ports(self) -> set[int]:
        ...


class StatusBackend(Protocol):
    def run(self, arguments: Sequence[str], *, quiet: bool = True) -> CommandResult:
        ...


class ConsoleCliBackend(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult:
        """Run a non-interactive console-cli command."""

    def run_interactive(self, arguments: Sequence[str]) -> int:
        """Run console-cli with the caller's terminal attached."""


class SonicConfigDbBackend:
    """Production ConfigDB backend using Generic Config Updater.

    ``prevalidate()`` builds one JSON patch for the complete candidate state
    and runs GenericUpdater with ``dry_run=True``. ``commit()`` then applies
    that exact prepared patch with ``dry_run=False``.

    SONiC-specific imports are intentionally delayed until construction or
    method execution so isolated unit tests can import this module without a
    full SONiC runtime environment.
    """

    def __init__(
        self,
        *,
        scope: str | None = None,
        config_db: Any | None = None,
        updater_factory: Any | None = None,
        config_loader: Any | None = None,
        patch_builder: Any | None = None,
        config_format: Any | None = None,
    ) -> None:
        if scope is None:
            from sonic_py_common import multi_asic

            scope = multi_asic.DEFAULT_NAMESPACE

        if config_db is None:
            from swsscommon.swsscommon import ConfigDBConnector

            config_db = ConfigDBConnector(
                use_unix_socket_path=True,
                namespace=scope,
            )
            config_db.connect()

        if updater_factory is None:
            from generic_config_updater.generic_updater import GenericUpdater

            updater_factory = GenericUpdater

        if config_loader is None:
            from generic_config_updater.gu_common import get_config_db_as_json

            config_loader = get_config_db_as_json

        if patch_builder is None:
            def patch_builder(current: Mapping[str, Any], candidate: Mapping[str, Any]):
                import jsonpatch

                return jsonpatch.make_patch(current, candidate)

        if config_format is None:
            from generic_config_updater.generic_updater import ConfigFormat

            config_format = ConfigFormat.CONFIGDB

        self._scope = scope
        self._config_db = config_db
        self._updater_factory = updater_factory
        self._config_loader = config_loader
        self._patch_builder = patch_builder
        self._config_format = config_format

        self._prepared_signature: tuple[Any, ...] | None = None
        self._prepared_patch: Any | None = None

    def get_table(
        self,
        table: str,
    ) -> Mapping[str, Mapping[str, Any]]:
        return self._config_db.get_table(table) or {}

    def get_entry(
        self,
        table: str,
        key: str,
    ) -> Mapping[str, Any]:
        return self._config_db.get_entry(table, key) or {}

    @staticmethod
    def _stringify_fields(fields: Mapping[str, Any]) -> dict[str, str]:
        return {
            str(field): str(value)
            for field, value in fields.items()
        }

    @staticmethod
    def _operation_signature(
        operations: Sequence[ConfigDbOperation],
    ) -> tuple[Any, ...]:
        signature: list[tuple[Any, ...]] = []

        for operation in operations:
            fields = None
            if operation.fields is not None:
                fields = tuple(
                    sorted(
                        (str(field), str(value))
                        for field, value in operation.fields.items()
                    )
                )

            signature.append(
                (
                    operation.action,
                    operation.table,
                    operation.key,
                    fields,
                )
            )

        return tuple(signature)

    def _build_patch(
        self,
        operations: Sequence[ConfigDbOperation],
    ) -> Any:
        current_config = self._config_loader(self._scope)
        candidate_config = copy.deepcopy(current_config)

        for operation in operations:
            if operation.action == "set":
                assert operation.fields is not None
                table = candidate_config.setdefault(operation.table, {})
                table[operation.key] = self._stringify_fields(operation.fields)
                continue

            if operation.action == "delete":
                table = candidate_config.get(operation.table)
                if table is None:
                    continue
                table.pop(operation.key, None)
                if not table:
                    candidate_config.pop(operation.table, None)
                continue

            raise ValueError(
                f"Unsupported ConfigDB operation '{operation.action}'"
            )

        return self._patch_builder(current_config, candidate_config)

    def _apply_patch(self, patch: Any, *, dry_run: bool) -> None:
        result = self._updater_factory().apply_patch(
            patch=patch,
            config_format=self._config_format,
            verbose=False,
            dry_run=dry_run,
            ignore_non_yang_tables=False,
            ignore_paths=None,
            sort=True,
        )

        if result not in (None, 0):
            phase = "validation" if dry_run else "commit"
            raise ConfigDbTransactionError(
                f"ConfigDB {phase} failed with result {result}"
            )

    def prevalidate(
        self,
        operations: Sequence[ConfigDbOperation],
    ) -> None:
        if not operations:
            raise ConfigDbValidationError(
                "At least one ConfigDB operation is required"
            )

        signature = self._operation_signature(operations)
        patch = self._build_patch(operations)

        try:
            self._apply_patch(patch, dry_run=True)
        except Exception as error:
            self._prepared_signature = None
            self._prepared_patch = None

            if isinstance(error, ConfigDbValidationError):
                raise

            raise ConfigDbValidationError(
                f"ConfigDB candidate validation failed: {error}"
            ) from error

        self._prepared_signature = signature
        self._prepared_patch = patch

    def commit(
        self,
        operations: Sequence[ConfigDbOperation],
    ) -> None:
        signature = self._operation_signature(operations)

        if (
            self._prepared_patch is None
            or self._prepared_signature != signature
        ):
            raise ConfigDbTransactionError(
                "ConfigDB operations were not prevalidated, or the "
                "operations changed after prevalidation"
            )

        patch = self._prepared_patch

        try:
            self._apply_patch(patch, dry_run=False)
        except Exception as error:
            if isinstance(error, ConfigDbTransactionError):
                raise

            raise ConfigDbTransactionError(
                f"ConfigDB commit failed: {error}"
            ) from error
        finally:
            self._prepared_signature = None
            self._prepared_patch = None

    def commit_direct(
        self,
        operations: Sequence[ConfigDbOperation],
    ) -> None:
        """Commit manager-validated operations directly to ConfigDB.

        This fast path is intended for interactive feature commands whose
        complete candidate state has already been validated by the shared
        console-server manager. It deliberately bypasses full-config GCU/CVL
        validation while retaining consistent error mapping.
        """

        if not operations:
            return

        try:
            for operation in operations:
                if operation.action == "set":
                    assert operation.fields is not None
                    self._config_db.set_entry(
                        operation.table,
                        operation.key,
                        self._stringify_fields(operation.fields),
                    )
                    continue

                if operation.action == "delete":
                    self._config_db.set_entry(
                        operation.table,
                        operation.key,
                        None,
                    )
                    continue

                raise ConfigDbTransactionError(
                    f"Unsupported ConfigDB operation '{operation.action}'"
                )
        except Exception as error:
            if isinstance(error, ConfigDbTransactionError):
                raise
            raise ConfigDbTransactionError(
                f"Direct ConfigDB commit failed: {error}"
            ) from error


class ConfigDbConsolePortProvider:
    """Discover valid console ports from ``CONSOLE_SERVER_PORT``.

    The platform boot path is expected to create one baseline row for every
    physical console port. The existing table keys therefore form the
    authoritative inventory used by CLI validation.
    """

    def __init__(self, config_db: ConfigDbBackend) -> None:
        self._config_db = config_db

    def get_valid_ports(self) -> set[int]:
        table = self._config_db.get_table(PORT_TABLE)
        if not table:
            raise InvalidConsolePort(
                f"{PORT_TABLE} is empty or unavailable"
            )

        valid_ports: set[int] = set()
        for key in table:
            try:
                port = int(key)
            except (TypeError, ValueError) as exc:
                raise InvalidConsolePort(
                    f"Invalid key {key!r} in {PORT_TABLE}"
                ) from exc

            if port < 1:
                raise InvalidConsolePort(
                    f"Invalid console port {port} in {PORT_TABLE}"
                )

            if port in valid_ports:
                raise InvalidConsolePort(
                    f"Duplicate console port {port} in {PORT_TABLE}"
                )

            valid_ports.add(port)

        return valid_ports


class SubprocessStatusBackend:
    """Execute the generic ConsoleServer ``seriald-status`` command."""

    def __init__(self, command: str = "/usr/local/bin/seriald-status") -> None:
        self._command = command

    def run(self, arguments: Sequence[str], *, quiet: bool = True) -> CommandResult:
        if not os.path.exists(self._command):
            raise ConsoleServerCommandError(f"{self._command} not found")

        command = [self._command, *map(str, arguments)]
        if quiet and "--quiet" not in command:
            command.append("--quiet")

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class SubprocessConsoleCliBackend:
    """Invoke the independent console-server application's public CLI.

    Passwords are passed through argv because this is the only interface
    currently supported by ``console-cli``. Never log full arguments.

    Interactive connect operations inherit stdin, stdout, and stderr from the
    SONiC ``connect`` command so terminal behavior is preserved.
    """

    def __init__(self, command: str = "/usr/local/bin/console-cli") -> None:
        self._command = command

    def _validate_command(self) -> None:
        if not os.path.exists(self._command):
            raise ConsoleServerCommandError(f"{self._command} not found")

    def run(self, arguments: Sequence[str]) -> CommandResult:
        self._validate_command()
        completed = subprocess.run(
            [self._command, *map(str, arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_interactive(self, arguments: Sequence[str]) -> int:
        """Run console-cli without redirecting any terminal stream."""

        self._validate_command()
        try:
            completed = subprocess.run(
                [self._command, *map(str, arguments)],
                check=False,
            )
        except OSError as error:
            raise ConsoleServerCommandError(
                f"Failed to execute {self._command}: {error}"
            ) from error
        return completed.returncode


# ---------------------------------------------------------------------------
# Pure parsing, normalization, and validation helpers
# ---------------------------------------------------------------------------


def parse_port_expression(
    expression: str,
    *,
    all_ports: Iterable[int] | None = None,
) -> list[int]:
    """Parse ``all``, ``1-5,8``, or ``1,3,7-9`` into explicit ports.

    Syntax errors are rejected; invalid fragments are never silently ignored.
    The returned list is sorted and deduplicated.
    """

    if not isinstance(expression, str) or not expression.strip():
        raise InvalidPortExpression("Port expression must not be empty")

    value = expression.strip()
    if value.lower() == "all":
        if all_ports is None:
            raise InvalidPortExpression("'all' requires the platform valid-port set")
        ports = sorted(set(all_ports))
        if not ports:
            raise InvalidPortExpression("The platform valid-port set is empty")
        return ports

    ports: list[int] = []
    seen: set[int] = set()

    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            raise InvalidPortExpression(f"Invalid empty item in '{expression}'")

        if "-" in part:
            if part.count("-") != 1:
                raise InvalidPortExpression(f"Invalid port range '{part}'")
            start_text, end_text = (item.strip() for item in part.split("-", 1))
            if not start_text.isdigit() or not end_text.isdigit():
                raise InvalidPortExpression(f"Invalid port range '{part}'")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise InvalidPortExpression(
                    f"Port range start must not exceed end: '{part}'"
                )
            values = range(start, end + 1)
        else:
            if not part.isdigit():
                raise InvalidPortExpression(f"Invalid port number '{part}'")
            values = (int(part),)

        for port in values:
            if port not in seen:
                seen.add(port)
                ports.append(port)

    return sorted(ports)


def validate_ports(ports: Sequence[int], *, valid_ports: set[int]) -> None:
    """Validate uniqueness and membership in the platform valid-port set."""

    if not ports:
        raise InvalidConsolePort("At least one console port is required")

    normalized: list[int] = []
    for port in ports:
        if isinstance(port, bool) or not isinstance(port, int):
            raise InvalidConsolePort(f"Invalid console port '{port}'")
        normalized.append(port)

    if len(set(normalized)) != len(normalized):
        raise DuplicateConsolePort("Duplicate console ports are not allowed")

    invalid = sorted(set(normalized) - valid_ports)
    if invalid:
        raise InvalidConsolePort(
            "Invalid console port(s): " + ", ".join(map(str, invalid))
        )


def normalize_group_ports(
    group_name: str,
    ports: Sequence[int],
) -> list[ConfigDbOperation]:
    """Convert ports into normalized ``CONSOLE_SERVER_GROUP_PORT`` rows."""

    name = _normalize_name(group_name, "group name")
    return [
        ConfigDbOperation(
            action="set",
            table=GROUP_PORT_TABLE,
            key=f"{name}|{port}",
            fields={},
        )
        for port in sorted(ports)
    ]


def normalize_port_label(
    port: int,
    label: str | None,
    *,
    current_label: str | None = None,
    entry_exists: bool = False,
) -> str:
    """Return the explicit label to store in ConfigDB.

    * new entry + omitted label -> ``COM<port>``;
    * existing entry + omitted label -> preserve current label;
    * explicit blank/whitespace label -> ``COM<port>``;
    * reserved labels are canonicalized to uppercase.
    """

    if label is None:
        if entry_exists:
            if current_label is None or not str(current_label).strip():
                raise MissingStoredPortLabel(
                    f"Existing console port {port} has no stored label"
                )
            normalized = str(current_label).strip()
        else:
            normalized = f"COM{port}"
    else:
        normalized = str(label).strip()
        if not normalized:
            normalized = f"COM{port}"

    match = _RESERVED_LABEL_RE.fullmatch(normalized)
    if match:
        normalized = f"COM{int(match.group(1))}"

    if not 1 <= len(normalized) <= 16:
        raise InvalidPortConfiguration("Label length must be between 1 and 16")

    return normalized


def validate_reserved_port_label(
    port: int,
    label: str,
    *,
    valid_ports: set[int],
) -> None:
    """Reject ``COM<M>`` when M is a different valid console port."""

    match = _RESERVED_LABEL_RE.fullmatch(label.strip())
    if not match:
        return

    reserved_port = int(match.group(1))
    if reserved_port in valid_ports and reserved_port != port:
        raise ReservedPortLabelConflict(
            f"Label 'COM{reserved_port}' is reserved for console port "
            f"{reserved_port}."
        )


def validate_unique_label(
    port: int,
    label: str,
    *,
    existing_labels: Mapping[int, str],
    valid_ports: set[int],
) -> None:
    """Validate reserved-label ownership and uniqueness against other ports."""

    validate_reserved_port_label(port, label, valid_ports=valid_ports)
    candidate_reserved = _RESERVED_LABEL_RE.fullmatch(label.strip()) is not None

    for existing_port, existing_label in existing_labels.items():
        if existing_port == port:
            continue
        if existing_label is None or not str(existing_label).strip():
            raise MissingStoredPortLabel(
                f"Console port {existing_port} has no stored label"
            )

        normalized_existing = str(existing_label).strip()
        existing_reserved = _RESERVED_LABEL_RE.fullmatch(normalized_existing) is not None

        if candidate_reserved or existing_reserved:
            equal = normalized_existing.casefold() == label.casefold()
        else:
            equal = normalized_existing == label

        if equal:
            raise DuplicatePortLabel(
                f"Label '{label}' is already assigned to console port "
                f"{existing_port}."
            )


def build_port_config(
    port: int,
    current: Mapping[str, Any],
    updates: Mapping[str, Any],
    *,
    valid_ports: set[int],
    existing_labels: Mapping[int, str],
) -> dict[str, Any]:
    """Build a complete, normalized, validated port ConfigDB entry."""

    validate_ports([port], valid_ports=valid_ports)

    unknown = set(updates) - PORT_FIELDS
    if unknown:
        raise InvalidPortConfiguration(
            "Unknown port field(s): " + ", ".join(sorted(unknown))
        )

    entry_exists = bool(current)
    candidate: dict[str, Any] = dict(PORT_DEFAULTS)
    candidate.update(dict(current))
    candidate.update(dict(updates))

    candidate["label"] = normalize_port_label(
        port,
        updates.get("label") if "label" in updates else None,
        current_label=current.get("label"),
        entry_exists=entry_exists,
    )

    candidate["baudrate"] = _to_int(candidate["baudrate"], "baudrate")
    candidate["databits"] = _to_int(candidate["databits"], "databits")
    candidate["stopbits"] = _to_int(candidate["stopbits"], "stopbits")
    candidate["max_clients"] = _to_int(candidate["max_clients"], "max_clients")
    candidate["idle_timeout"] = _to_int(candidate["idle_timeout"], "idle_timeout")
    candidate["parity"] = str(candidate["parity"]).lower()
    candidate["flowcontrol"] = str(candidate["flowcontrol"]).lower()
    candidate["mode"] = str(candidate["mode"]).lower()

    if candidate["baudrate"] not in ALLOWED_BAUDRATES:
        raise InvalidPortConfiguration("Unsupported baudrate")
    if candidate["databits"] not in ALLOWED_DATABITS:
        raise InvalidPortConfiguration("databits must be one of 5, 6, 7, 8")
    if candidate["parity"] not in ALLOWED_PARITY:
        raise InvalidPortConfiguration("Unsupported parity")
    if candidate["stopbits"] not in ALLOWED_STOPBITS:
        raise InvalidPortConfiguration("stopbits must be 1 or 2")
    if candidate["flowcontrol"] not in ALLOWED_FLOWCONTROL:
        raise InvalidPortConfiguration("Unsupported flowcontrol")
    if candidate["mode"] not in ALLOWED_MODES:
        raise InvalidPortConfiguration("mode must be exclusive or shared")
    if not 1 <= candidate["max_clients"] <= 4:
        raise InvalidPortConfiguration("max_clients must be between 1 and 4")
    if not 0 <= candidate["idle_timeout"] <= 86400:
        raise InvalidPortConfiguration("idle_timeout must be between 0 and 86400")

    validate_unique_label(
        port,
        candidate["label"],
        existing_labels=existing_labels,
        valid_ports=valid_ports,
    )
    return candidate



def normalize_username(username: str) -> str:
    """Normalize and validate a username against the YANG model."""

    name = _normalize_name(username, "username")
    if not 1 <= len(name) <= 32:
        raise ConsoleServerManagerError(
            "username length must be between 1 and 32"
        )
    if not _USERNAME_RE.fullmatch(name):
        raise ConsoleServerManagerError(
            "username must match [A-Za-z_][A-Za-z0-9_-]*"
        )
    return name


def validate_password(password: str) -> None:
    """Validate password length without exposing its value."""

    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        raise PasswordRequired(
            "password length must be between 1 and 128"
        )



# ---------------------------------------------------------------------------
# SONiC orchestration manager
# ---------------------------------------------------------------------------


class SonicConsoleServerManager:
    """Orchestrate seriald-status commands and SONiC ConfigDB updates."""

    def __init__(
        self,
        *,
        config_db: ConfigDbBackend,
        port_provider: PortProvider,
        status_backend: StatusBackend,
        console_cli_backend: ConsoleCliBackend,
    ) -> None:
        self._config_db = config_db
        self._port_provider = port_provider
        self._status = status_backend
        self._console_cli = console_cli_backend

    def get_valid_ports(self) -> set[int]:
        ports = set(self._port_provider.get_valid_ports())
        if not ports:
            raise InvalidConsolePort("No valid console ports were discovered")
        return ports

    def write_transaction(self, operations: Sequence[ConfigDbOperation]) -> None:
        """CVL-prevalidate and atomically commit ConfigDB-only operations."""

        if not operations:
            return
        try:
            self._config_db.prevalidate(operations)
        except Exception as exc:
            raise ConfigDbValidationError(str(exc)) from exc
        try:
            self._config_db.commit(operations)
        except Exception as exc:
            raise ConfigDbTransactionError(str(exc)) from exc

    def get_port_configs(self) -> list[dict[str, Any]]:
        """Return configured console ports, sorted numerically by port."""

        records: list[dict[str, Any]] = []
        for raw_key, fields in self._config_db.get_table(PORT_TABLE).items():
            if isinstance(raw_key, tuple):
                if len(raw_key) != 1:
                    raise ConfigDbTransactionError(
                        f"Invalid key {raw_key!r} in {PORT_TABLE}"
                    )
                raw_port = raw_key[0]
            else:
                raw_port = raw_key

            try:
                port = int(raw_port)
            except (TypeError, ValueError) as error:
                raise ConfigDbTransactionError(
                    f"Invalid port key {raw_key!r} in {PORT_TABLE}"
                ) from error

            record = {"port": port}
            record.update(dict(fields))
            records.append(record)

        return sorted(records, key=lambda item: item["port"])

    def get_user_configs(self) -> list[dict[str, Any]]:
        """Return configured users with their ConfigDB group mappings."""

        users = {
            str(key): dict(fields)
            for key, fields in self._config_db.get_table(USER_TABLE).items()
        }
        memberships: dict[str, set[str]] = {}
        for raw_key in self._config_db.get_table(USER_GROUP_TABLE):
            username, group_name = _decode_compound_key(
                raw_key,
                parts=2,
                table=USER_GROUP_TABLE,
            )
            memberships.setdefault(username, set()).add(group_name)

        records: list[dict[str, Any]] = []
        for username in sorted(set(users) | set(memberships)):
            record = {"username": username}
            record.update(users.get(username, {}))
            record["groups"] = sorted(memberships.get(username, set()))
            records.append(record)
        return records

    def get_group_configs(self) -> list[dict[str, Any]]:
        """Return configured groups with their ConfigDB port mappings."""

        groups = {
            str(key): dict(fields)
            for key, fields in self._config_db.get_table(GROUP_TABLE).items()
        }
        memberships: dict[str, set[int]] = {}
        for raw_key in self._config_db.get_table(GROUP_PORT_TABLE):
            group_name, raw_port = _decode_compound_key(
                raw_key,
                parts=2,
                table=GROUP_PORT_TABLE,
            )
            try:
                port = int(raw_port)
            except ValueError as error:
                raise ConfigDbTransactionError(
                    f"Invalid port {raw_port!r} in {GROUP_PORT_TABLE}"
                ) from error
            memberships.setdefault(group_name, set()).add(port)

        records: list[dict[str, Any]] = []
        for group_name in sorted(set(groups) | set(memberships)):
            record = {"group": group_name}
            record.update(groups.get(group_name, {}))
            record["ports"] = sorted(memberships.get(group_name, set()))
            records.append(record)
        return records

    def resolve_port_by_label(self, label: str) -> int:
        """Resolve an exact, case-sensitive port label to its line ID."""

        if not isinstance(label, str) or not label.strip():
            raise InvalidPortConfiguration(
                "Console port label must not be empty"
            )

        requested_label = label.strip()
        matches: list[int] = []

        for record in self.get_port_configs():
            port = record["port"]
            stored_label = record.get("label")
            if stored_label is None or not str(stored_label).strip():
                raise MissingStoredPortLabel(
                    f"Console port {port} has no stored label"
                )
            if str(stored_label) == requested_label:
                matches.append(port)

        if not matches:
            raise InvalidConsolePort(
                f"No console port has label '{requested_label}'"
            )

        if len(matches) > 1:
            ports = ", ".join(str(port) for port in sorted(matches))
            raise DuplicatePortLabel(
                f"Label '{requested_label}' is assigned to multiple "
                f"console ports: {ports}"
            )

        return matches[0]

    def connect_line(self, port: int) -> int:
        """Validate a line and start an interactive console-cli connection."""

        valid_ports = self.get_valid_ports()
        validate_ports([port], valid_ports=valid_ports)

        try:
            return self._console_cli.run_interactive(
                ["connect", str(port)]
            )
        except ConsoleServerManagerError:
            raise
        except Exception as error:
            raise ConsoleServerCommandError(
                f"Failed to connect to console port {port}: {error}"
            ) from error

    def set_port_config(self, port: int, updates: Mapping[str, Any]) -> None:
        valid_ports = self.get_valid_ports()
        current = dict(self._config_db.get_entry(PORT_TABLE, str(port)))
        labels = self._get_existing_labels()
        candidate = build_port_config(
            port,
            current,
            updates,
            valid_ports=valid_ports,
            existing_labels=labels,
        )
        changed_updates = {
            key: candidate[key]
            for key in updates
            if key not in current or str(current[key]) != str(candidate[key])
        }
        if not changed_updates:
            return

        operations = [
            ConfigDbOperation("set", PORT_TABLE, str(port), candidate)
        ]

        # Port candidates are fully normalized and feature-validated by
        # build_port_config(). Use the dedicated fast path instead of running
        # full-config GCU/CVL validation for every interactive leaf update.
        # Only send values that differ from ConfigDB to avoid unnecessary
        # seriald reconfiguration and ConfigDB writes.
        runtime_commands = self._port_status_commands(port, changed_updates)
        rollback_values = {
            key: (current.get(key) if key in current else candidate[key])
            for key in changed_updates
        }
        rollback_commands = self._port_status_commands(port, rollback_values)

        for command in runtime_commands:
            self._run_status(command)
        try:
            self._commit_direct(operations)
        except Exception as original_error:
            try:
                for command in reversed(rollback_commands):
                    self._run_status(command)
            except Exception as rollback_error:
                raise RuntimeRollbackError(
                    original_error, rollback_error
                ) from original_error
            raise

    def set_group_config(
        self,
        group_name: str,
        *,
        role: str = "console_user",
        ports: str,
    ) -> None:
        """Create or replace one group through the interactive fast path.

        Group role and port membership are validated before runtime is changed.
        Runtime receives one combined command, followed by one direct ConfigDB
        batch. If the ConfigDB batch fails, runtime is restored to its previous
        state.
        """

        name = _normalize_name(group_name, "group name")
        normalized_role = str(role).lower()
        if normalized_role not in ALLOWED_GROUP_ROLES:
            raise ConsoleServerManagerError(f"Unsupported role '{role}'")

        valid_ports = self.get_valid_ports()
        candidate_ports = parse_port_expression(
            ports,
            all_ports=valid_ports,
        )
        validate_ports(candidate_ports, valid_ports=valid_ports)

        current_group = dict(
            self._config_db.get_entry(GROUP_TABLE, name)
        )
        current_role = str(
            current_group.get("role", "console_user")
        ).lower()

        current_table = self._config_db.get_table(GROUP_PORT_TABLE)
        current_keys: list[str] = []
        current_ports: list[int] = []
        for raw_key in current_table:
            key_group, key_port = _decode_compound_key(
                raw_key,
                parts=2,
                table=GROUP_PORT_TABLE,
            )
            if key_group != name:
                continue

            current_keys.append(
                _encode_compound_key(key_group, key_port)
            )
            try:
                current_ports.append(int(key_port))
            except ValueError as error:
                raise ConfigDbTransactionError(
                    f"Invalid port {key_port!r} in {GROUP_PORT_TABLE}"
                ) from error

        current_ports.sort()
        if (
            current_group
            and current_role == normalized_role
            and current_ports == candidate_ports
        ):
            return

        operations: list[ConfigDbOperation] = [
            ConfigDbOperation(
                "set",
                GROUP_TABLE,
                name,
                {"role": normalized_role},
            )
        ]
        operations.extend(
            ConfigDbOperation("delete", GROUP_PORT_TABLE, key)
            for key in current_keys
        )
        operations.extend(normalize_group_ports(name, candidate_ports))

        self._run_status(
            [
                "config-group",
                name,
                "--role",
                normalized_role,
                "--ports",
                _ports_csv(candidate_ports),
            ]
        )

        try:
            self._commit_direct(operations)
        except Exception as original_error:
            rollback = ["config-group", name]
            if current_group:
                rollback.extend(
                    [
                        "--role",
                        current_role,
                        "--ports",
                        _ports_csv(current_ports),
                    ]
                )
            else:
                rollback = ["config-no-group", name]

            self._rollback_status(rollback, original_error)
            raise

    def create_or_update_group(
        self,
        group_name: str,
        *,
        role: str | None = None,
    ) -> None:
        """Legacy metadata-only group API retained for non-CLI callers."""

        name = _normalize_name(group_name, "group name")
        current = dict(self._config_db.get_entry(GROUP_TABLE, name))
        candidate = dict(current)

        if role is not None:
            normalized_role = str(role).lower()
            if normalized_role not in ALLOWED_GROUP_ROLES:
                raise ConsoleServerManagerError(f"Unsupported role '{role}'")
            candidate["role"] = normalized_role

        if not candidate:
            candidate["role"] = "console_user"

        operations = [ConfigDbOperation("set", GROUP_TABLE, name, candidate)]
        self._prevalidate(operations)

        args = ["config-group", name]
        if role is not None:
            args += ["--role", str(candidate["role"])]
        self._run_status(args)
        try:
            self._commit(operations)
        except Exception as original_error:
            rollback = ["config-group", name]
            if current.get("role") is not None:
                rollback += ["--role", str(current["role"])]
            elif not current:
                rollback = ["config-no-group", name]
            self._rollback_status(rollback, original_error)
            raise

    def set_group_ports(self, group_name: str, expression: str) -> None:
        """Legacy port-membership API retained for non-CLI callers."""

        name = _normalize_name(group_name, "group name")
        group = dict(self._config_db.get_entry(GROUP_TABLE, name))
        if not group:
            raise ConsoleServerManagerError(f"Group '{name}' does not exist")

        self.set_group_config(
            name,
            role=str(group.get("role", "console_user")),
            ports=expression,
        )

    def delete_group(self, group_name: str) -> None:
        """Delete a group and all mappings through the direct fast path."""

        name = _normalize_name(group_name, "group name")
        group = dict(self._config_db.get_entry(GROUP_TABLE, name))

        group_ports: dict[str, dict[str, Any]] = {}
        rollback_ports: list[int] = []
        for raw_key, fields in self._config_db.get_table(
            GROUP_PORT_TABLE
        ).items():
            key_group, key_port = _decode_compound_key(
                raw_key,
                parts=2,
                table=GROUP_PORT_TABLE,
            )
            if key_group != name:
                continue

            canonical_key = _encode_compound_key(key_group, key_port)
            group_ports[canonical_key] = dict(fields)
            try:
                rollback_ports.append(int(key_port))
            except ValueError as error:
                raise ConfigDbTransactionError(
                    f"Invalid port {key_port!r} in {GROUP_PORT_TABLE}"
                ) from error

        user_groups: dict[str, dict[str, Any]] = {}
        for raw_key, fields in self._config_db.get_table(
            USER_GROUP_TABLE
        ).items():
            username, key_group = _decode_compound_key(
                raw_key,
                parts=2,
                table=USER_GROUP_TABLE,
            )
            if key_group == name:
                user_groups[
                    _encode_compound_key(username, key_group)
                ] = dict(fields)

        if not group and not group_ports and not user_groups:
            return

        operations: list[ConfigDbOperation] = [
            ConfigDbOperation("delete", USER_GROUP_TABLE, key)
            for key in user_groups
        ]
        operations.extend(
            ConfigDbOperation("delete", GROUP_PORT_TABLE, key)
            for key in group_ports
        )
        operations.append(
            ConfigDbOperation("delete", GROUP_TABLE, name)
        )

        self._run_status(["config-no-group", name])
        try:
            self._commit_direct(operations)
        except Exception as original_error:
            rollback = ["config-group", name]
            if group.get("role") is not None:
                rollback.extend(["--role", str(group["role"])])

            rollback_ports.sort()
            if rollback_ports:
                rollback.extend(
                    ["--ports", _ports_csv(rollback_ports)]
                )

            self._rollback_status(rollback, original_error)
            raise

    def set_user_config(
        self,
        username: str,
        password: str | None,
        role: str | None,
        groups: list[str] | None,
    ) -> None:
        name = normalize_username(username)
        if password is not None:
            validate_password(password)

        normalized_role = None if role is None else str(role).lower()
        if normalized_role is not None and normalized_role not in ALLOWED_USER_ROLES:
            raise ConsoleServerManagerError(f"Unsupported role '{role}'")

        normalized_groups = None
        if groups is not None:
            normalized_groups = [_normalize_name(group, "group name") for group in groups]
            if len(set(normalized_groups)) != len(normalized_groups):
                raise ConsoleServerManagerError("Duplicate group names are not allowed")
            missing = [group for group in normalized_groups if not self._config_db.get_entry(GROUP_TABLE, group)]
            if missing:
                raise ConsoleServerManagerError("Unknown group(s): " + ", ".join(sorted(missing)))

        current_user = dict(self._config_db.get_entry(USER_TABLE, name))
        current_user_groups: dict[str, dict[str, Any]] = {}
        for raw_key, fields in self._config_db.get_table(USER_GROUP_TABLE).items():
            key_user, key_group = _decode_compound_key(raw_key, parts=2, table=USER_GROUP_TABLE)
            if key_user == name:
                current_user_groups[_encode_compound_key(key_user, key_group)] = dict(fields)

        candidate_user = dict(current_user)
        if normalized_role is not None:
            candidate_user["role"] = normalized_role
        if not candidate_user:
            candidate_user["role"] = "none"

        operations: list[ConfigDbOperation] = [ConfigDbOperation("set", USER_TABLE, name, candidate_user)]
        if normalized_groups is not None:
            operations.extend(ConfigDbOperation("delete", USER_GROUP_TABLE, key) for key in current_user_groups)
            operations.extend(ConfigDbOperation("set", USER_GROUP_TABLE, f"{name}|{group}", {}) for group in sorted(normalized_groups))

        arguments = ["config", "user", "add", name]
        if password is not None:
            arguments.extend(["--password", password])
        if normalized_role is not None:
            arguments.extend(["--role", normalized_role])
        if normalized_groups is not None:
            arguments.extend(["--groups", ",".join(normalized_groups)])
        self._run_console_cli(arguments)
        self._commit_direct(operations)

    def set_user_password(self, username: str, password: str) -> None:
        name = normalize_username(username)
        validate_password(password)
        self._run_console_cli(["config", "user", "add", name, "--password", password])

    def delete_user(self, username: str) -> None:
        name = normalize_username(username)
        user = dict(self._config_db.get_entry(USER_TABLE, name))
        mappings: dict[str, dict[str, Any]] = {}
        for raw_key, fields in self._config_db.get_table(USER_GROUP_TABLE).items():
            key_user, key_group = _decode_compound_key(raw_key, parts=2, table=USER_GROUP_TABLE)
            if key_user == name:
                mappings[_encode_compound_key(key_user, key_group)] = dict(fields)
        if not user and not mappings:
            return
        operations: list[ConfigDbOperation] = [ConfigDbOperation("delete", USER_GROUP_TABLE, key) for key in mappings]
        operations.append(ConfigDbOperation("delete", USER_TABLE, name))
        self._run_console_cli(["config", "user", "delete", name])
        self._commit_direct(operations)

    # ---- private helpers -------------------------------------------------

    def _get_existing_labels(self) -> dict[int, str]:
        labels: dict[int, str] = {}
        for key, fields in self._config_db.get_table(PORT_TABLE).items():
            try:
                port = int(key)
            except (TypeError, ValueError):
                continue
            if "label" in fields:
                labels[port] = str(fields["label"])
        return labels

    def _prevalidate(self, operations: Sequence[ConfigDbOperation]) -> None:
        try:
            self._config_db.prevalidate(operations)
        except Exception as exc:
            raise ConfigDbValidationError(str(exc)) from exc

    def _commit(self, operations: Sequence[ConfigDbOperation]) -> None:
        try:
            self._config_db.commit(operations)
        except Exception as exc:
            raise ConfigDbTransactionError(str(exc)) from exc

    def _commit_direct(self, operations: Sequence[ConfigDbOperation]) -> None:
        try:
            self._config_db.commit_direct(operations)
        except Exception as exc:
            if isinstance(exc, ConfigDbTransactionError):
                raise
            raise ConfigDbTransactionError(str(exc)) from exc

    def _run_status(self, arguments: Sequence[str]) -> CommandResult:
        result = self._status.run(arguments, quiet=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ConsoleServerCommandError(
                detail or f"seriald-status command failed: {' '.join(arguments)}"
            )
        return result

    def _run_console_cli(self, arguments: Sequence[str]) -> CommandResult:
        result = self._console_cli.run(arguments)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ConsoleServerCommandError(detail or "console-cli command failed")
        return result

    def _rollback_status(
        self,
        arguments: Sequence[str],
        original_error: Exception,
    ) -> None:
        try:
            self._run_status(arguments)
        except Exception as rollback_error:
            raise RuntimeRollbackError(original_error, rollback_error) from original_error

    @staticmethod
    def _port_status_commands(
        port: int, values: Mapping[str, Any]
    ) -> list[list[str]]:
        serial_fields = {
            "baudrate",
            "databits",
            "parity",
            "stopbits",
            "flowcontrol",
        }
        operation_fields = {
            "mode",
            "max_clients",
            "idle_timeout",
            "label",
        }
        unknown = set(values) - serial_fields - operation_fields
        if unknown:
            raise InvalidPortConfiguration(
                "Unsupported runtime field(s): " + ", ".join(sorted(unknown))
            )

        option_names = {
            "max_clients": "max-clients",
            "idle_timeout": "idle-timeout",
        }
        commands: list[list[str]] = []
        for command_name, fields in (
            ("config-port", serial_fields),
            ("config-op", operation_fields),
        ):
            selected = [(key, value) for key, value in values.items() if key in fields]
            if not selected:
                continue
            command = [command_name, str(port)]
            for key, value in selected:
                command.extend([f"--{option_names.get(key, key)}", str(value)])
            commands.append(command)

        if not commands:
            raise InvalidPortConfiguration("No port settings were provided")
        return commands



def create_default_manager(
    *,
    scope: str | None = None,
    status_command: str = "/usr/local/bin/seriald-status",
    console_cli_command: str = "/usr/local/bin/console-cli",
) -> SonicConsoleServerManager:
    """Create the production SONiC ConsoleServer manager."""

    config_db = SonicConfigDbBackend(scope=scope)

    return SonicConsoleServerManager(
        config_db=config_db,
        port_provider=ConfigDbConsolePortProvider(config_db),
        status_backend=SubprocessStatusBackend(status_command),
        console_cli_backend=SubprocessConsoleCliBackend(console_cli_command),
    )


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------



def _decode_compound_key(
    key: Any,
    *,
    parts: int,
    table: str,
) -> tuple[str, ...]:
    """Normalize ConfigDB compound keys returned as tuples or pipe strings.

    ``ConfigDBConnector.get_table()`` may return multi-key table keys as
    tuples, while JSON/GCU operations use the canonical ``a|b`` form.
    """

    if isinstance(key, (tuple, list)):
        values = tuple(str(value) for value in key)
    else:
        values = tuple(str(key).split("|", parts - 1))

    if len(values) != parts or any(not value for value in values):
        raise ConfigDbTransactionError(
            f"Invalid key {key!r} returned for {table}"
        )
    return values


def _encode_compound_key(*parts: Any) -> str:
    return "|".join(str(part) for part in parts)


def _normalize_name(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConsoleServerManagerError(f"{field} must not be empty")
    return value.strip()


def _to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise InvalidPortConfiguration(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPortConfiguration(f"{field} must be an integer") from exc


def _ports_csv(ports: Sequence[int]) -> str:
    return ",".join(str(port) for port in ports)
