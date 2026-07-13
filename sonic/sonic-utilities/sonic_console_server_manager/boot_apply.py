"""Replay SONiC ConfigDB console-server state into the running seriald daemon.

This module is intentionally SONiC-side.  It never writes
``/etc/seriald/config.json``.  That file remains the independent application's
standalone/bootstrap configuration; ConfigDB is authoritative after SONiC boot.
"""

from __future__ import annotations

import json
import logging
import pwd
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .manager import (
    ALLOWED_GROUP_ROLES,
    ALLOWED_USER_ROLES,
    GROUP_PORT_TABLE,
    GROUP_TABLE,
    PORT_FIELDS,
    PORT_TABLE,
    PRODUCT_INFO_KEY,
    PRODUCT_INFO_TABLE,
    USER_GROUP_TABLE,
    USER_TABLE,
    ConfigDbBackend,
    ConsoleServerCommandError,
    ConsoleServerManagerError,
    StatusBackend,
    SubprocessConsoleCliBackend,
    SubprocessStatusBackend,
    SonicConfigDbBackend,
    build_port_config,
)

LOG = logging.getLogger("console-server-config-apply")


@dataclass(frozen=True)
class ApplySummary:
    ports: int = 0
    groups: int = 0
    users: int = 0
    unmanaged_users: int = 0


class BootApplyError(ConsoleServerManagerError):
    """One or more ConfigDB values could not be applied to runtime."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ConsoleServerBootApply:
    """Validate a ConfigDB snapshot and reconcile seriald runtime with it.

    Boot reconciliation policy (keep this list beside the implementation so
    ownership decisions are easy to audit):

    * Ports: apply every ``CONSOLE_SERVER_PORT`` ConfigDB row.
    * Groups: replace runtime groups with ConfigDB groups and remove extras.
    * User metadata: apply ConfigDB role/group metadata to existing users.
    * Extra Linux/runtime users: preserve them and log that they are unmanaged.
    * Passwords: never read, request, log, or modify them.
    * Product info: validate only; never apply it to seriald runtime.

    The apply path is runtime-only.  It must not update ConfigDB and must never
    save changes into ``/etc/seriald/config.json``.
    """

    def __init__(
        self,
        *,
        config_db: ConfigDbBackend,
        status_backend: StatusBackend,
        console_cli_backend: SubprocessConsoleCliBackend,
        local_user_exists: Callable[[str], bool] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config_db = config_db
        self._status = status_backend
        self._console_cli = console_cli_backend
        self._local_user_exists = local_user_exists or self._pwd_user_exists
        self._log = logger or LOG

    @staticmethod
    def _pwd_user_exists(username: str) -> bool:
        try:
            pwd.getpwnam(username)
        except KeyError:
            return False
        return True

    def apply(self) -> ApplySummary:
        errors: list[str] = []
        ports = self._load_ports(errors)
        groups = self._load_groups(errors)
        users = self._load_users(errors)
        self._validate_product_info(errors)
        if errors:
            raise BootApplyError(errors)

        applied_ports = self._apply_ports(ports, errors)
        applied_groups = self._apply_groups(groups, errors)
        applied_users, unmanaged_users = self._apply_users(users, errors)

        if errors:
            raise BootApplyError(errors)
        return ApplySummary(
            ports=applied_ports,
            groups=applied_groups,
            users=applied_users,
            unmanaged_users=unmanaged_users,
        )

    def _load_ports(self, errors: list[str]) -> list[tuple[int, dict[str, Any]]]:
        table = self._config_db.get_table(PORT_TABLE)
        if not table:
            errors.append(f"{PORT_TABLE} is empty")
            return []

        raw_entries: list[tuple[int, dict[str, Any]]] = []
        labels: dict[int, str] = {}
        valid_ports: set[int] = set()
        for raw_key, fields in table.items():
            try:
                key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
                port = int(key)
                if port < 1:
                    raise ValueError
            except (TypeError, ValueError, IndexError):
                errors.append(f"invalid {PORT_TABLE} key {raw_key!r}")
                continue
            valid_ports.add(port)
            entry = dict(fields)
            if "label" in entry:
                labels[port] = str(entry["label"])
            raw_entries.append((port, entry))

        normalized: list[tuple[int, dict[str, Any]]] = []
        for port, entry in raw_entries:
            unknown = set(entry) - PORT_FIELDS
            if unknown:
                errors.append(
                    f"port {port}: unsupported field(s): {', '.join(sorted(unknown))}"
                )
                continue
            try:
                # An existing ConfigDB row must already be complete.  Passing
                # it through the shared validator also checks labels, ranges,
                # role-independent serial settings, and canonical types.
                candidate = build_port_config(
                    port,
                    entry,
                    {},
                    valid_ports=valid_ports,
                    existing_labels=labels,
                )
            except Exception as error:  # preserve the shared error wording
                errors.append(f"port {port}: {error}")
                continue
            normalized.append((port, candidate))
        return sorted(normalized)

    def _load_groups(self, errors: list[str]) -> dict[str, dict[str, Any]]:
        groups = {
            str(key): dict(fields)
            for key, fields in self._config_db.get_table(GROUP_TABLE).items()
        }
        ports_by_group: dict[str, set[int]] = {}
        for raw_key in self._config_db.get_table(GROUP_PORT_TABLE):
            parts = tuple(raw_key) if isinstance(raw_key, tuple) else tuple(str(raw_key).split("|", 1))
            if len(parts) != 2:
                errors.append(f"invalid {GROUP_PORT_TABLE} key {raw_key!r}")
                continue
            group_name, raw_port = map(str, parts)
            try:
                port = int(raw_port)
            except ValueError:
                errors.append(f"group {group_name}: invalid port {raw_port!r}")
                continue
            ports_by_group.setdefault(group_name, set()).add(port)

        result: dict[str, dict[str, Any]] = {}
        valid_ports = {
            port for port, _ in self._load_ports([])
        }
        for name in sorted(set(groups) | set(ports_by_group)):
            role = str(groups.get(name, {}).get("role", "console_user")).lower()
            ports = sorted(ports_by_group.get(name, set()))
            if name not in groups:
                errors.append(f"group {name}: membership exists without {GROUP_TABLE} row")
                continue
            if role not in ALLOWED_GROUP_ROLES:
                errors.append(f"group {name}: unsupported role {role!r}")
                continue
            invalid_ports = sorted(set(ports) - valid_ports)
            if invalid_ports:
                errors.append(
                    f"group {name}: invalid port(s): {', '.join(map(str, invalid_ports))}"
                )
                continue
            result[name] = {"role": role, "ports": ports}
        return result

    def _load_users(self, errors: list[str]) -> dict[str, dict[str, Any]]:
        users = {
            str(key): dict(fields)
            for key, fields in self._config_db.get_table(USER_TABLE).items()
        }
        groups_by_user: dict[str, set[str]] = {}
        for raw_key in self._config_db.get_table(USER_GROUP_TABLE):
            parts = tuple(raw_key) if isinstance(raw_key, tuple) else tuple(str(raw_key).split("|", 1))
            if len(parts) != 2:
                errors.append(f"invalid {USER_GROUP_TABLE} key {raw_key!r}")
                continue
            username, group_name = map(str, parts)
            groups_by_user.setdefault(username, set()).add(group_name)

        configured_groups = set(self._config_db.get_table(GROUP_TABLE))
        result: dict[str, dict[str, Any]] = {}
        for username in sorted(set(users) | set(groups_by_user)):
            if username not in users:
                errors.append(f"user {username}: membership exists without {USER_TABLE} row")
                continue
            role = str(users[username].get("role", "none")).lower()
            groups = sorted(groups_by_user.get(username, set()))
            if role not in ALLOWED_USER_ROLES:
                errors.append(f"user {username}: unsupported role {role!r}")
                continue
            missing = sorted(set(groups) - set(map(str, configured_groups)))
            if missing:
                errors.append(f"user {username}: unknown group(s): {', '.join(missing)}")
                continue
            result[username] = {"role": role, "groups": groups}
        return result

    def _validate_product_info(self, errors: list[str]) -> None:
        # Product information describes platform limits.  It is deliberately
        # validation-only: no command is sent to seriald for this table.
        info = dict(self._config_db.get_entry(PRODUCT_INFO_TABLE, PRODUCT_INFO_KEY))
        required = ("base_port", "max_ports", "max_users", "max_groups")
        if not info:
            errors.append(f"{PRODUCT_INFO_TABLE}|{PRODUCT_INFO_KEY} is missing")
            return
        values: dict[str, int] = {}
        for field in required:
            try:
                value = int(info[field])
                if value < 1:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors.append(f"product info: invalid or missing {field}")
                continue
            values[field] = value
        if set(values) == set(required) and values["base_port"] + values["max_ports"] > 65535:
            errors.append("product info: TCP port range exceeds 65535")

    def _apply_ports(self, ports: list[tuple[int, dict[str, Any]]], errors: list[str]) -> int:
        count = 0
        for port, values in ports:
            serial = ["config-port", str(port)]
            operation = ["config-op", str(port)]
            for field in ("baudrate", "databits", "parity", "stopbits", "flowcontrol"):
                serial.extend([f"--{field}", str(values[field])])
            for field in ("mode", "max_clients", "idle_timeout", "label"):
                option = field.replace("_", "-")
                operation.extend([f"--{option}", str(values[field])])
            try:
                self._run_status(serial)
                self._run_status(operation)
                count += 1
            except Exception as error:
                errors.append(f"port {port}: {error}")
        return count

    def _runtime_group_names(self, errors: list[str]) -> set[str]:
        try:
            result = self._status.run(["show-running-config", "--groups"], quiet=True)
            if result.returncode != 0:
                raise ConsoleServerCommandError(result.stderr.strip() or result.stdout.strip())
            payload = json.loads(result.stdout or "{}")
            groups = payload.get("groups", {})
            if not isinstance(groups, Mapping):
                raise ValueError("groups is not an object")
            return set(map(str, groups))
        except Exception as error:
            errors.append(f"cannot read runtime groups: {error}")
            return set()

    def _apply_groups(self, groups: dict[str, dict[str, Any]], errors: list[str]) -> int:
        runtime_groups = self._runtime_group_names(errors)
        if any(item.startswith("cannot read runtime groups:") for item in errors):
            return 0

        # ConfigDB owns the complete group set in SONiC mode.  Remove bootstrap
        # or stale runtime groups that are absent from ConfigDB.
        for extra in sorted(runtime_groups - set(groups)):
            try:
                self._run_status(["config-no-group", extra])
            except Exception as error:
                errors.append(f"remove extra group {extra}: {error}")

        count = 0
        for name, data in groups.items():
            command = [
                "config-group", name,
                "--role", data["role"],
                "--ports", ",".join(map(str, data["ports"])),
            ]
            try:
                self._run_status(command)
                count += 1
            except Exception as error:
                errors.append(f"group {name}: {error}")
        return count

    def _runtime_user_names(self, errors: list[str]) -> set[str]:
        try:
            result = self._status.run(["show-running-config", "--users"], quiet=True)
            if result.returncode != 0:
                raise ConsoleServerCommandError(result.stderr.strip() or result.stdout.strip())
            payload = json.loads(result.stdout or "{}")
            users = payload.get("users", {})
            if not isinstance(users, Mapping):
                raise ValueError("users is not an object")
            return set(map(str, users))
        except Exception as error:
            errors.append(f"cannot read runtime users: {error}")
            return set()

    def _apply_users(self, users: dict[str, dict[str, Any]], errors: list[str]) -> tuple[int, int]:
        runtime_users = self._runtime_user_names(errors)
        if any(item.startswith("cannot read runtime users:") for item in errors):
            return 0, 0

        # Runtime users absent from ConfigDB are deliberately preserved.  User
        # deletion could remove a Linux account or credentials that SONiC does
        # not own and cannot reconstruct, so boot apply only reports them.
        extra_runtime_users = sorted(runtime_users - set(users))
        for username in extra_runtime_users:
            self._log.warning(
                "Preserving unmanaged runtime user %s: absent from ConfigDB",
                username,
            )

        count = 0
        unmanaged = len(extra_runtime_users)
        for username, data in users.items():
            if not self._local_user_exists(username):
                unmanaged += 1
                self._log.warning(
                    "Preserving unmanaged ConfigDB user %s: no local Linux/NSS account exists",
                    username,
                )
                continue

            # Passwords are intentionally absent.  Supplying only role/groups
            # updates metadata for the already-existing account and cannot
            # create, replace, or expose a password.
            arguments = ["config", "user", "add", username, "--role", data["role"]]
            arguments.extend(["--groups", ",".join(data["groups"])])
            try:
                result = self._console_cli.run(arguments)
                if result.returncode != 0:
                    raise ConsoleServerCommandError(result.stderr.strip() or result.stdout.strip())
                count += 1
            except Exception as error:
                errors.append(f"user {username}: {error}")
        return count, unmanaged

    def _run_status(self, arguments: list[str]) -> None:
        result = self._status.run(arguments, quiet=True)
        if result.returncode != 0:
            raise ConsoleServerCommandError(
                result.stderr.strip() or result.stdout.strip() or "seriald-status command failed"
            )


def create_default_boot_apply() -> ConsoleServerBootApply:
    return ConsoleServerBootApply(
        config_db=SonicConfigDbBackend(),
        status_backend=SubprocessStatusBackend(),
        console_cli_backend=SubprocessConsoleCliBackend(),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(levelname)s: %(message)s")
    try:
        summary = create_default_boot_apply().apply()
    except Exception as error:
        LOG.error("Console-server boot apply failed: %s", error)
        return 1
    LOG.info(
        "Console-server boot apply complete: ports=%d groups=%d users=%d unmanaged_users=%d",
        summary.ports,
        summary.groups,
        summary.users,
        summary.unmanaged_users,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
