"""Generate the complete SONiC console-server runtime configuration.

The independent console-server application remains SONiC-agnostic.  In SONiC
mode this module combines application/platform fields from the standalone
bootstrap file with SONiC-owned configurable state from ConfigDB, then writes a
complete runtime snapshot for ``server.py``.

The bootstrap file is read-only.  This module never starts/stops services and
never modifies Linux/NSS users, groups, or passwords.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import pwd
import tempfile
from pathlib import Path
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
    ConsoleServerManagerError,
    SonicConfigDbBackend,
    build_port_config,
)

LOG = logging.getLogger("console-server-config-generate")


class ConfigGenerationError(ConsoleServerManagerError):
    """The ConfigDB/bootstrap candidate cannot form a valid runtime file."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


class ConsoleServerConfigGenerator:
    """Build and atomically write a complete runtime JSON snapshot.

    Startup ownership policy (keep this list beside the implementation):

    * Ports: include every ConfigDB port row; ConfigDB-owned fields override
      the matching bootstrap line while application/platform fields remain.
    * Groups: replace bootstrap groups with exactly the ConfigDB groups.
    * User metadata: include ConfigDB role/group metadata only when that user
      already exists through Linux/NSS.  Linux/NSS is validation-only.
    * Extra Linux/bootstrap users: preserve bootstrap metadata and log them as
      unmanaged; discard memberships to groups absent from ConfigDB.
    * Passwords: never read from ConfigDB, emit, log, generate, or modify them.
    * Product info: validate and map required limits into the application's
      existing ``info`` structure; it is not an independent runtime object.

    This code never modifies ``/etc/seriald/config.json`` and never creates,
    updates, or deletes Linux/NSS users or groups.
    """

    def __init__(
        self,
        *,
        config_db: ConfigDbBackend,
        local_user_exists: Callable[[str], bool] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config_db = config_db
        self._local_user_exists = local_user_exists or self._pwd_user_exists
        self._log = logger or LOG

    @staticmethod
    def _pwd_user_exists(username: str) -> bool:
        try:
            pwd.getpwnam(username)
        except KeyError:
            return False
        return True

    @staticmethod
    def _simple_key(raw_key: Any) -> str:
        if isinstance(raw_key, tuple):
            if len(raw_key) != 1:
                raise ValueError(f"invalid simple key {raw_key!r}")
            return str(raw_key[0])
        return str(raw_key)

    @staticmethod
    def _compound_key(raw_key: Any, table: str) -> tuple[str, str]:
        parts = tuple(raw_key) if isinstance(raw_key, tuple) else tuple(str(raw_key).split("|", 1))
        if len(parts) != 2:
            raise ValueError(f"invalid {table} key {raw_key!r}")
        return str(parts[0]), str(parts[1])

    @staticmethod
    def load_bootstrap(path: str | os.PathLike[str]) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigGenerationError(f"cannot load bootstrap config {path}: {error}") from error
        if not isinstance(value, dict):
            raise ConfigGenerationError("bootstrap config must be a JSON object")
        for section in ("info", "lines", "groups", "users"):
            if not isinstance(value.get(section), dict):
                raise ConfigGenerationError(f"bootstrap config: {section} must be an object")
        return value

    def generate(self, bootstrap: Mapping[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        candidate = copy.deepcopy(dict(bootstrap))

        product_info = self._load_product_info(errors)
        ports = self._load_ports(product_info.get("max_ports"), errors)
        groups = self._load_groups(set(ports), errors)
        users = self._load_users(set(groups), errors)

        bootstrap_lines = candidate.get("lines")
        bootstrap_users = candidate.get("users")
        if not isinstance(bootstrap_lines, dict):
            errors.append("bootstrap config: lines must be an object")
            bootstrap_lines = {}
        if not isinstance(bootstrap_users, dict):
            errors.append("bootstrap config: users must be an object")
            bootstrap_users = {}

        generated_lines: dict[str, dict[str, Any]] = {}
        for port, port_config in sorted(ports.items()):
            key = str(port)
            base_line = bootstrap_lines.get(key)
            if not isinstance(base_line, dict):
                errors.append(f"bootstrap config: missing line {port}")
                continue
            line = copy.deepcopy(base_line)
            for field in PORT_FIELDS:
                line[field] = port_config[field]
            generated_lines[key] = line

        generated_users = self._merge_users(
            bootstrap_users=bootstrap_users,
            configured_users=users,
            configured_groups=set(groups),
            errors=errors,
        )

        if errors:
            raise ConfigGenerationError(errors)

        info = copy.deepcopy(candidate.get("info", {}))
        info.update(
            {
                "base_port": product_info["base_port"],
                "no_of_port": product_info["max_ports"],
                "no_of_user": product_info["max_users"],
                "no_of_group": product_info["max_groups"],
            }
        )
        candidate["info"] = info
        candidate["lines"] = generated_lines
        candidate["groups"] = {
            name: {"role": value["role"], "port_list": value["ports"]}
            for name, value in sorted(groups.items())
        }
        candidate["users"] = generated_users
        return candidate

    def generate_file(
        self,
        *,
        bootstrap_path: str | os.PathLike[str],
        output_path: str | os.PathLike[str],
    ) -> dict[str, Any]:
        candidate = self.generate(self.load_bootstrap(bootstrap_path))
        self.write_atomic(candidate, output_path)
        return candidate

    def _load_product_info(self, errors: list[str]) -> dict[str, int]:
        info = dict(self._config_db.get_entry(PRODUCT_INFO_TABLE, PRODUCT_INFO_KEY))
        required = ("base_port", "max_ports", "max_users", "max_groups")
        if not info:
            errors.append(f"{PRODUCT_INFO_TABLE}|{PRODUCT_INFO_KEY} is missing")
            return {}
        result: dict[str, int] = {}
        for field in required:
            try:
                value = int(info[field])
                if value < 1:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors.append(f"product info: invalid or missing {field}")
                continue
            result[field] = value
        if set(result) == set(required) and result["base_port"] + result["max_ports"] > 65535:
            errors.append("product info: TCP port range exceeds 65535")
        return result

    def _load_ports(self, max_ports: int | None, errors: list[str]) -> dict[int, dict[str, Any]]:
        table = self._config_db.get_table(PORT_TABLE)
        if not table:
            errors.append(f"{PORT_TABLE} is empty")
            return {}

        raw_entries: dict[int, dict[str, Any]] = {}
        labels: dict[int, str] = {}
        for raw_key, fields in table.items():
            try:
                port = int(self._simple_key(raw_key))
                if port < 1 or port in raw_entries:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"invalid or duplicate {PORT_TABLE} key {raw_key!r}")
                continue
            entry = dict(fields)
            raw_entries[port] = entry
            if "label" in entry:
                labels[port] = str(entry["label"])

        if max_ports is not None:
            expected = set(range(1, max_ports + 1))
            actual = set(raw_entries)
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            if missing:
                errors.append(f"{PORT_TABLE}: missing port(s): {', '.join(map(str, missing))}")
            if extra:
                errors.append(f"{PORT_TABLE}: unexpected port(s): {', '.join(map(str, extra))}")

        valid_ports = set(raw_entries)
        result: dict[int, dict[str, Any]] = {}
        for port, entry in sorted(raw_entries.items()):
            unknown = set(entry) - PORT_FIELDS
            missing_fields = PORT_FIELDS - set(entry)
            if unknown:
                errors.append(f"port {port}: unsupported field(s): {', '.join(sorted(unknown))}")
            if missing_fields:
                errors.append(f"port {port}: missing field(s): {', '.join(sorted(missing_fields))}")
            if unknown or missing_fields:
                continue
            try:
                result[port] = build_port_config(
                    port,
                    entry,
                    {},
                    valid_ports=valid_ports,
                    existing_labels=labels,
                )
            except Exception as error:
                errors.append(f"port {port}: {error}")
        return result

    def _load_groups(self, valid_ports: set[int], errors: list[str]) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for raw_key, fields in self._config_db.get_table(GROUP_TABLE).items():
            try:
                name = self._simple_key(raw_key)
            except ValueError as error:
                errors.append(str(error))
                continue
            groups[name] = dict(fields)

        ports_by_group: dict[str, set[int]] = {}
        for raw_key in self._config_db.get_table(GROUP_PORT_TABLE):
            try:
                group_name, raw_port = self._compound_key(raw_key, GROUP_PORT_TABLE)
                port = int(raw_port)
            except (TypeError, ValueError) as error:
                errors.append(str(error))
                continue
            ports_by_group.setdefault(group_name, set()).add(port)

        result: dict[str, dict[str, Any]] = {}
        for name in sorted(set(groups) | set(ports_by_group)):
            if name not in groups:
                errors.append(f"group {name}: membership exists without {GROUP_TABLE} row")
                continue
            role = str(groups[name].get("role", "console_user")).lower()
            ports = sorted(ports_by_group.get(name, set()))
            if role not in ALLOWED_GROUP_ROLES:
                errors.append(f"group {name}: unsupported role {role!r}")
                continue
            invalid = sorted(set(ports) - valid_ports)
            if invalid:
                errors.append(f"group {name}: invalid port(s): {', '.join(map(str, invalid))}")
                continue
            result[name] = {"role": role, "ports": ports}
        return result

    def _load_users(self, configured_groups: set[str], errors: list[str]) -> dict[str, dict[str, Any]]:
        users: dict[str, dict[str, Any]] = {}
        for raw_key, fields in self._config_db.get_table(USER_TABLE).items():
            try:
                username = self._simple_key(raw_key)
            except ValueError as error:
                errors.append(str(error))
                continue
            users[username] = dict(fields)

        groups_by_user: dict[str, set[str]] = {}
        for raw_key in self._config_db.get_table(USER_GROUP_TABLE):
            try:
                username, group_name = self._compound_key(raw_key, USER_GROUP_TABLE)
            except ValueError as error:
                errors.append(str(error))
                continue
            groups_by_user.setdefault(username, set()).add(group_name)

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
            missing = sorted(set(groups) - configured_groups)
            if missing:
                errors.append(f"user {username}: unknown group(s): {', '.join(missing)}")
                continue
            result[username] = {"role": role, "groups": groups}
        return result

    def _merge_users(
        self,
        *,
        bootstrap_users: Mapping[str, Any],
        configured_users: Mapping[str, Mapping[str, Any]],
        configured_groups: set[str],
        errors: list[str],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}

        for username, value in sorted(configured_users.items()):
            if not self._local_user_exists(username):
                self._log.warning(
                    "Skipping ConfigDB user %s: no local Linux/NSS account exists; "
                    "Linux/NSS is validation-only and is not modified",
                    username,
                )
                continue
            result[username] = {
                "role": value["role"],
                "groups": list(value["groups"]),
            }

        for raw_username, raw_value in sorted(bootstrap_users.items(), key=lambda item: str(item[0])):
            username = str(raw_username)
            if username in configured_users:
                continue
            if not isinstance(raw_value, Mapping):
                errors.append(f"bootstrap user {username}: entry must be an object")
                continue
            role = str(raw_value.get("role", "none")).lower()
            if role not in ALLOWED_USER_ROLES:
                errors.append(f"bootstrap user {username}: unsupported role {role!r}")
                continue
            raw_groups = raw_value.get("groups", [])
            if not isinstance(raw_groups, list):
                errors.append(f"bootstrap user {username}: groups must be a list")
                continue
            groups = sorted({str(group) for group in raw_groups if str(group) in configured_groups})
            removed = sorted({str(group) for group in raw_groups} - configured_groups)
            if removed:
                self._log.warning(
                    "Removing undefined group membership(s) from unmanaged bootstrap user %s: %s",
                    username,
                    ", ".join(removed),
                )
            self._log.warning(
                "Preserving unmanaged bootstrap user %s: absent from ConfigDB",
                username,
            )
            result[username] = {"role": role, "groups": groups}

        return result

    @staticmethod
    def write_atomic(candidate: Mapping[str, Any], output_path: str | os.PathLike[str]) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                os.fchmod(stream.fileno(), 0o600)
                json.dump(candidate, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, output)
            temporary_name = None
            os.chmod(output, 0o600)
            directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SONiC console-server runtime JSON")
    parser.add_argument("--bootstrap-config", default="/etc/seriald/config.json")
    parser.add_argument("--output", default="/run/seriald/config.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(levelname)s: %(message)s")
    args = _build_parser().parse_args(argv)
    try:
        generator = ConsoleServerConfigGenerator(config_db=SonicConfigDbBackend())
        candidate = generator.generate_file(
            bootstrap_path=args.bootstrap_config,
            output_path=args.output,
        )
    except (ConfigGenerationError, ConsoleServerManagerError, OSError) as error:
        LOG.error("%s", error)
        return 1
    LOG.info(
        "Generated runtime config: ports=%d groups=%d users=%d output=%s",
        len(candidate.get("lines", {})),
        len(candidate.get("groups", {})),
        len(candidate.get("users", {})),
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
