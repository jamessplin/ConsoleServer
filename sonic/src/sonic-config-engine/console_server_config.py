"""Generate SONiC ConfigDB tables for the console-server feature.

The platform/HWSKU input file is intentionally similar to SONiC platform
configuration files such as ``port_config.ini``: it describes the product
limits and factory defaults for console-server ports, groups, and user
metadata.  This module converts that platform description into ConfigDB
schema tables consumed by sonic-utilities and the console-server manager.

Input lookup order:

1. explicit ``console_server_config_file`` argument;
2. HWSKU-level file:
   ``/usr/share/sonic/device/<platform>/<hwsku>/console_server.json``;
3. platform-level fallback:
   ``/usr/share/sonic/device/<platform>/console_server.json``.

If no input file exists, an empty dictionary is returned so non-console-server
platforms are unaffected.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Any, Mapping

CONSOLE_SERVER_PRODUCT_INFO_TABLE = "CONSOLE_SERVER_PRODUCT_INFO"
CONSOLE_SERVER_PORT_TABLE = "CONSOLE_SERVER_PORT"
CONSOLE_SERVER_GROUP_TABLE = "CONSOLE_SERVER_GROUP"
CONSOLE_SERVER_GROUP_PORT_TABLE = "CONSOLE_SERVER_GROUP_PORT"
CONSOLE_SERVER_USER_TABLE = "CONSOLE_SERVER_USER"
CONSOLE_SERVER_USER_GROUP_TABLE = "CONSOLE_SERVER_USER_GROUP"

DEFAULT_DEVICE_ROOT = "/usr/share/sonic/device"
DEFAULT_PRODUCT_KEY = "global"

REQUIRED_INFO_FIELDS = {
    "base_port",
    "no_of_user",
    "no_of_group",
    "no_of_port",
}

REQUIRED_PORT_FIELDS = {
    "label",
    "mode",
    "max_clients",
    "idle_timeout",
    "baudrate",
    "databits",
    "stopbits",
    "parity",
    "flowcontrol",
}

ALLOWED_MODES = {"shared", "exclusive"}
ALLOWED_PARITIES = {"none", "even", "odd"}
ALLOWED_FLOWCONTROL = {"none", "rtscts", "xonxoff"}
ALLOWED_GROUP_ROLES = {"console_user", "admin", "operator"}
ALLOWED_USER_ROLES = {"admin", "console_user", "operator", "none"}
ALLOWED_DATABITS = {5, 6, 7, 8}
ALLOWED_STOPBITS = {1, 2}
ALLOWED_BAUDRATES = {
    50,
    75,
    110,
    134,
    150,
    200,
    300,
    600,
    1200,
    1800,
    2400,
    4800,
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
    500000,
    576000,
    921600,
    1000000,
    1152000,
    1500000,
    2000000,
    2500000,
    3000000,
    3500000,
    4000000,
}


class ConsoleServerConfigError(ValueError):
    """Raised when console_server.json is malformed or inconsistent."""


def _as_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConsoleServerConfigError(f"{path} must be an object")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConsoleServerConfigError(f"{path} must be a list")
    return value


def _require_fields(mapping: Mapping[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required - set(mapping))
    if missing:
        raise ConsoleServerConfigError(
            f"{path} is missing required field(s): {', '.join(missing)}"
        )


def _int(value: Any, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConsoleServerConfigError(f"{path} must be an integer")

    if minimum is not None and number < minimum:
        raise ConsoleServerConfigError(f"{path} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ConsoleServerConfigError(f"{path} must be <= {maximum}")
    return number


def _str(value: Any, path: str) -> str:
    if value is None:
        raise ConsoleServerConfigError(f"{path} must not be null")
    text = str(value).strip()
    if not text:
        raise ConsoleServerConfigError(f"{path} must not be empty")
    return text


def _enum(value: Any, allowed: set[str], path: str) -> str:
    text = _str(value, path).lower()
    if text not in allowed:
        raise ConsoleServerConfigError(
            f"{path} has unsupported value {value!r}; expected one of {sorted(allowed)}"
        )
    return text


def _resolve_console_server_config_file(
    hwsku: str,
    platform: str | None,
    *,
    console_server_config_file: str | None = None,
    device_root: str = DEFAULT_DEVICE_ROOT,
) -> str | None:
    if console_server_config_file:
        return console_server_config_file

    if not platform:
        return None

    candidates = [
        os.path.join(device_root, platform, hwsku, "console_server.json"),
        os.path.join(device_root, platform, "console_server.json"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_json_file(path: str) -> Mapping[str, Any]:
    try:
        with open(path, "r") as stream:
            payload = json.load(stream, object_pairs_hook=OrderedDict)
    except OSError as error:
        raise ConsoleServerConfigError(f"Failed to read {path}: {error}")
    except json.JSONDecodeError as error:
        raise ConsoleServerConfigError(f"Invalid JSON in {path}: {error}")
    return _as_mapping(payload, "console_server.json")


def _normalize_info(info: Mapping[str, Any]) -> OrderedDict[str, str]:
    _require_fields(info, REQUIRED_INFO_FIELDS, "info")

    base_port = _int(info["base_port"], "info.base_port", minimum=1, maximum=65535)
    max_ports = _int(info["no_of_port"], "info.no_of_port", minimum=1, maximum=65535)
    max_users = _int(info["no_of_user"], "info.no_of_user", minimum=1)
    max_groups = _int(info["no_of_group"], "info.no_of_group", minimum=1)

    if base_port + max_ports > 65535:
        raise ConsoleServerConfigError(
            "info.base_port + info.no_of_port must not exceed 65535"
        )

    return OrderedDict(
        [
            ("base_port", str(base_port)),
            ("max_ports", str(max_ports)),
            ("max_users", str(max_users)),
            ("max_groups", str(max_groups)),
        ]
    )


def _normalize_ports(
    ports: Mapping[str, Any],
    *,
    max_ports: int,
) -> OrderedDict[str, OrderedDict[str, str]]:
    normalized: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
    labels: dict[str, str] = {}

    if len(ports) != max_ports:
        raise ConsoleServerConfigError(
            f"ports contains {len(ports)} entries, expected info.no_of_port={max_ports}"
        )

    for raw_port in sorted(ports, key=lambda item: _int(item, f"ports.{item}")):
        port = _int(raw_port, f"ports.{raw_port}", minimum=1, maximum=max_ports)
        key = str(port)
        if key in normalized:
            raise ConsoleServerConfigError(f"Duplicate port entry {key}")

        entry = _as_mapping(ports[raw_port], f"ports.{raw_port}")
        _require_fields(entry, REQUIRED_PORT_FIELDS, f"ports.{raw_port}")

        label = _str(entry["label"], f"ports.{raw_port}.label")
        label_key = label.lower()
        if label_key in labels:
            raise ConsoleServerConfigError(
                f"Duplicate console-server label {label!r} on ports {labels[label_key]} and {key}"
            )
        labels[label_key] = key

        baudrate = _int(entry["baudrate"], f"ports.{raw_port}.baudrate", minimum=1)
        if baudrate not in ALLOWED_BAUDRATES:
            raise ConsoleServerConfigError(
                f"ports.{raw_port}.baudrate has unsupported value {baudrate}"
            )

        databits = _int(entry["databits"], f"ports.{raw_port}.databits")
        if databits not in ALLOWED_DATABITS:
            raise ConsoleServerConfigError(
                f"ports.{raw_port}.databits has unsupported value {databits}"
            )

        stopbits = _int(entry["stopbits"], f"ports.{raw_port}.stopbits")
        if stopbits not in ALLOWED_STOPBITS:
            raise ConsoleServerConfigError(
                f"ports.{raw_port}.stopbits has unsupported value {stopbits}"
            )

        normalized[key] = OrderedDict(
            [
                ("label", label),
                ("mode", _enum(entry["mode"], ALLOWED_MODES, f"ports.{raw_port}.mode")),
                ("max_clients", str(_int(entry["max_clients"], f"ports.{raw_port}.max_clients", minimum=1))),
                ("idle_timeout", str(_int(entry["idle_timeout"], f"ports.{raw_port}.idle_timeout", minimum=0, maximum=86400))),
                ("baudrate", str(baudrate)),
                ("databits", str(databits)),
                ("stopbits", str(stopbits)),
                ("parity", _enum(entry["parity"], ALLOWED_PARITIES, f"ports.{raw_port}.parity")),
                ("flowcontrol", _enum(entry["flowcontrol"], ALLOWED_FLOWCONTROL, f"ports.{raw_port}.flowcontrol")),
            ]
        )

    expected_ports = {str(port) for port in range(1, max_ports + 1)}
    actual_ports = set(normalized)
    if actual_ports != expected_ports:
        missing = sorted(expected_ports - actual_ports, key=int)
        extra = sorted(actual_ports - expected_ports, key=int)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("extra " + ", ".join(extra))
        raise ConsoleServerConfigError("ports must be contiguous 1..no_of_port: " + "; ".join(details))

    return normalized


def _normalize_groups(
    groups: Mapping[str, Any],
    *,
    valid_ports: set[int],
    max_groups: int,
) -> tuple[OrderedDict[str, OrderedDict[str, str]], OrderedDict[str, dict[str, str]]]:
    if len(groups) > max_groups:
        raise ConsoleServerConfigError(
            f"groups contains {len(groups)} entries, exceeds info.no_of_group={max_groups}"
        )

    group_table: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
    group_port_table: OrderedDict[str, dict[str, str]] = OrderedDict()

    for group_name in sorted(groups):
        name = _str(group_name, f"groups.{group_name}")
        entry = _as_mapping(groups[group_name], f"groups.{group_name}")
        _require_fields(entry, {"role", "port_list"}, f"groups.{group_name}")

        role = _enum(entry["role"], ALLOWED_GROUP_ROLES, f"groups.{group_name}.role")
        port_list = _as_list(entry["port_list"], f"groups.{group_name}.port_list")
        if not port_list:
            raise ConsoleServerConfigError(f"groups.{group_name}.port_list must not be empty")

        normalized_ports: list[int] = []
        for index, raw_port in enumerate(port_list):
            port = _int(raw_port, f"groups.{group_name}.port_list[{index}]", minimum=1)
            normalized_ports.append(port)

        duplicate_ports = sorted({port for port in normalized_ports if normalized_ports.count(port) > 1})
        if duplicate_ports:
            raise ConsoleServerConfigError(
                f"groups.{group_name}.port_list contains duplicate port(s): "
                + ", ".join(map(str, duplicate_ports))
            )

        invalid_ports = sorted(set(normalized_ports) - valid_ports)
        if invalid_ports:
            raise ConsoleServerConfigError(
                f"groups.{group_name}.port_list contains invalid port(s): "
                + ", ".join(map(str, invalid_ports))
            )

        group_table[name] = OrderedDict([("role", role)])
        for port in sorted(normalized_ports):
            group_port_table[f"{name}|{port}"] = {}

    return group_table, group_port_table


def _normalize_users(
    users: Mapping[str, Any],
    *,
    valid_groups: set[str],
    max_users: int,
) -> tuple[OrderedDict[str, OrderedDict[str, str]], OrderedDict[str, dict[str, str]]]:
    if len(users) > max_users:
        raise ConsoleServerConfigError(
            f"users contains {len(users)} entries, exceeds info.no_of_user={max_users}"
        )

    user_table: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
    user_group_table: OrderedDict[str, dict[str, str]] = OrderedDict()

    for username in sorted(users):
        name = _str(username, f"users.{username}")
        entry = _as_mapping(users[username], f"users.{username}")
        _require_fields(entry, {"role", "groups"}, f"users.{username}")

        role = _enum(entry["role"], ALLOWED_USER_ROLES, f"users.{username}.role")
        groups = _as_list(entry["groups"], f"users.{username}.groups")
        if not groups:
            raise ConsoleServerConfigError(f"users.{username}.groups must not be empty")

        normalized_groups: list[str] = []
        for index, raw_group in enumerate(groups):
            group_name = _str(raw_group, f"users.{username}.groups[{index}]")
            normalized_groups.append(group_name)

        duplicate_groups = sorted({group for group in normalized_groups if normalized_groups.count(group) > 1})
        if duplicate_groups:
            raise ConsoleServerConfigError(
                f"users.{username}.groups contains duplicate group(s): "
                + ", ".join(duplicate_groups)
            )

        invalid_groups = sorted(set(normalized_groups) - valid_groups)
        if invalid_groups:
            raise ConsoleServerConfigError(
                f"users.{username}.groups references undefined group(s): "
                + ", ".join(invalid_groups)
            )

        user_table[name] = OrderedDict([("role", role)])
        for group_name in sorted(normalized_groups):
            user_group_table[f"{name}|{group_name}"] = {}

    return user_table, user_group_table


def generate_console_server_config_db(payload: Mapping[str, Any]) -> OrderedDict[str, Any]:
    """Convert a parsed console_server.json payload to ConfigDB tables."""

    root = _as_mapping(payload, "console_server.json")
    _require_fields(root, {"info", "ports", "groups", "users"}, "console_server.json")

    info = _normalize_info(_as_mapping(root["info"], "info"))
    max_ports = int(info["max_ports"])
    max_users = int(info["max_users"])
    max_groups = int(info["max_groups"])

    ports = _normalize_ports(_as_mapping(root["ports"], "ports"), max_ports=max_ports)
    valid_ports = {int(port) for port in ports}

    group_table, group_port_table = _normalize_groups(
        _as_mapping(root["groups"], "groups"),
        valid_ports=valid_ports,
        max_groups=max_groups,
    )

    user_table, user_group_table = _normalize_users(
        _as_mapping(root["users"], "users"),
        valid_groups=set(group_table),
        max_users=max_users,
    )

    return OrderedDict(
        [
            (CONSOLE_SERVER_PRODUCT_INFO_TABLE, OrderedDict([(DEFAULT_PRODUCT_KEY, info)])),
            (CONSOLE_SERVER_PORT_TABLE, ports),
            (CONSOLE_SERVER_GROUP_TABLE, group_table),
            (CONSOLE_SERVER_GROUP_PORT_TABLE, group_port_table),
            (CONSOLE_SERVER_USER_TABLE, user_table),
            (CONSOLE_SERVER_USER_GROUP_TABLE, user_group_table),
        ]
    )


def get_console_server_config(
    hwsku: str,
    platform: str | None = None,
    *,
    console_server_config_file: str | None = None,
    device_root: str = DEFAULT_DEVICE_ROOT,
) -> OrderedDict[str, Any]:
    """Return generated console-server ConfigDB tables for a platform/HWSKU.

    Returns an empty dictionary when no ``console_server.json`` file exists so
    platforms that do not support this feature keep their existing behavior.
    """

    path = _resolve_console_server_config_file(
        hwsku,
        platform,
        console_server_config_file=console_server_config_file,
        device_root=device_root,
    )
    if path is None:
        return OrderedDict()

    return generate_console_server_config_db(_load_json_file(path))
