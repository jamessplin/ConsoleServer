import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from console_server_config import (
    ConsoleServerConfigError,
    generate_console_server_config_db,
    get_console_server_config,
)


def make_payload(max_clients=1):
    ports = {}
    for port in range(1, 25):
        ports[str(port)] = {
            "label": f"COM{port}",
            "mode": "shared",
            "max_clients": max_clients,
            "idle_timeout": 600,
            "baudrate": 115200,
            "databits": 8,
            "stopbits": 1,
            "parity": "none",
            "flowcontrol": "none",
        }
    return {
        "info": {
            "base_port": 35000,
            "no_of_user": 16,
            "no_of_group": 16,
            "no_of_port": 24,
        },
        "ports": ports,
        "groups": {
            "Group_Default": {
                "port_list": list(range(1, 25)),
                "role": "console_user",
            }
        },
        "users": {
            "admin": {
                "groups": ["Group_Default"],
                "role": "admin",
            }
        },
    }


def test_generate_console_server_config_db_tables():
    result = generate_console_server_config_db(make_payload())

    assert result["CONSOLE_SERVER_PRODUCT_INFO"]["global"] == {
        "base_port": "35000",
        "max_ports": "24",
        "max_users": "16",
        "max_groups": "16",
    }

    assert len(result["CONSOLE_SERVER_PORT"]) == 24
    assert result["CONSOLE_SERVER_PORT"]["1"] == {
        "label": "COM1",
        "mode": "shared",
        "max_clients": "1",
        "idle_timeout": "600",
        "baudrate": "115200",
        "databits": "8",
        "stopbits": "1",
        "parity": "none",
        "flowcontrol": "none",
    }
    assert result["CONSOLE_SERVER_PORT"]["24"]["label"] == "COM24"

    assert result["CONSOLE_SERVER_GROUP"] == {
        "Group_Default": {"role": "console_user"}
    }
    assert len(result["CONSOLE_SERVER_GROUP_PORT"]) == 24
    assert result["CONSOLE_SERVER_GROUP_PORT"]["Group_Default|1"] == {}
    assert result["CONSOLE_SERVER_GROUP_PORT"]["Group_Default|24"] == {}

    assert result["CONSOLE_SERVER_USER"] == {"admin": {"role": "admin"}}
    assert result["CONSOLE_SERVER_USER_GROUP"] == {"admin|Group_Default": {}}


def test_get_console_server_config_prefers_hwsku_level(tmp_path):
    platform = "arm64-test-r0"
    hwsku = "test_hwsku"
    platform_dir = tmp_path / platform
    hwsku_dir = platform_dir / hwsku
    hwsku_dir.mkdir(parents=True)

    platform_payload = make_payload(max_clients=2)
    hwsku_payload = make_payload(max_clients=1)
    (platform_dir / "console_server.json").write_text(json.dumps(platform_payload))
    (hwsku_dir / "console_server.json").write_text(json.dumps(hwsku_payload))

    result = get_console_server_config(hwsku, platform, device_root=str(tmp_path))
    assert result["CONSOLE_SERVER_PORT"]["1"]["max_clients"] == "1"


def test_get_console_server_config_uses_platform_fallback(tmp_path):
    platform = "arm64-test-r0"
    hwsku = "test_hwsku"
    platform_dir = tmp_path / platform
    platform_dir.mkdir(parents=True)
    (platform_dir / "console_server.json").write_text(json.dumps(make_payload(max_clients=3)))

    result = get_console_server_config(hwsku, platform, device_root=str(tmp_path))
    assert result["CONSOLE_SERVER_PORT"]["1"]["max_clients"] == "3"


def test_get_console_server_config_returns_empty_when_missing(tmp_path):
    assert get_console_server_config("missing", "platform", device_root=str(tmp_path)) == {}


def test_rejects_duplicate_labels():
    payload = make_payload()
    payload["ports"]["2"]["label"] = "COM1"

    with pytest.raises(ConsoleServerConfigError, match="Duplicate console-server label"):
        generate_console_server_config_db(payload)


def test_rejects_group_port_outside_valid_range():
    payload = make_payload()
    payload["groups"]["Group_Default"]["port_list"].append(25)

    with pytest.raises(ConsoleServerConfigError, match="invalid port"):
        generate_console_server_config_db(payload)


def test_rejects_user_unknown_group():
    payload = make_payload()
    payload["users"]["admin"]["groups"] = ["Missing_Group"]

    with pytest.raises(ConsoleServerConfigError, match="undefined group"):
        generate_console_server_config_db(payload)


def test_rejects_non_contiguous_ports():
    payload = make_payload()
    payload["ports"].pop("24")
    payload["ports"]["25"] = copy.deepcopy(payload["ports"]["23"])
    payload["ports"]["25"]["label"] = "COM25"

    with pytest.raises(ConsoleServerConfigError, match="<= 24"):
        generate_console_server_config_db(payload)


def test_rejects_tcp_port_overflow():
    payload = make_payload()
    payload["info"]["base_port"] = 65520

    with pytest.raises(ConsoleServerConfigError, match="must not exceed 65535"):
        generate_console_server_config_db(payload)
