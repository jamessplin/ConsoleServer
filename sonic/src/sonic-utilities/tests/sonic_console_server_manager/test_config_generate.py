import json
import logging
import stat

import pytest

from sonic_console_server_manager.config_generate import (
    ConfigGenerationError,
    ConsoleServerConfigGenerator,
)


class FakeConfigDb:
    def __init__(self, tables):
        self.tables = tables

    def get_table(self, table):
        return self.tables.get(table, {})

    def get_entry(self, table, key):
        return self.tables.get(table, {}).get(key, {})


def base_tables(port_count=2):
    ports = {}
    group_ports = {}
    for port in range(1, port_count + 1):
        ports[str(port)] = {
            "baudrate": "9600" if port == 1 else "115200",
            "databits": "8",
            "parity": "none",
            "stopbits": "1",
            "flowcontrol": "xonxoff" if port == 1 else "none",
            "mode": "shared",
            "max_clients": "1",
            "idle_timeout": "600",
            "label": f"SONIC{port}",
        }
        group_ports[("operators", str(port))] = {}
    return {
        "CONSOLE_SERVER_PORT": ports,
        "CONSOLE_SERVER_GROUP": {"operators": {"role": "operator"}},
        "CONSOLE_SERVER_GROUP_PORT": group_ports,
        "CONSOLE_SERVER_USER": {
            "admin": {"role": "admin"},
            "missing": {"role": "none"},
        },
        "CONSOLE_SERVER_USER_GROUP": {("admin", "operators"): {}},
        "CONSOLE_SERVER_PRODUCT_INFO": {
            "global": {
                "base_port": "35000",
                "max_ports": str(port_count),
                "max_users": "16",
                "max_groups": "16",
            }
        },
    }


def bootstrap(port_count=2):
    return {
        "info": {
            "base_port": 10000,
            "no_of_user": 4,
            "no_of_group": 4,
            "no_of_port": port_count,
            "platform_marker": "keep",
        },
        "listen": {"host": "127.0.0.1", "port": 25001},
        "keepalive_ms": 10000,
        "future_top_level": {"preserve": True},
        "lines": {
            str(port): {
                "name": f"COM{port}",
                "device": f"/dev/ttyTEST{port}",
                "echo": True,
                "window_ms": 800,
                "fakeserial": False,
                "ser2net_host": "127.0.0.1",
                "ser2net_port": 50000 + port,
                "ser2net_config": f"ser2net_cfg/cs{port}.yaml",
                "interface": "rs232",
                "baudrate": 57600,
                "databits": 7,
                "parity": "odd",
                "stopbits": 2,
                "flowcontrol": "none",
                "mode": "exclusive",
                "max_clients": 2,
                "idle_timeout": 30,
                "label": f"BOOT{port}",
            }
            for port in range(1, port_count + 1)
        },
        "groups": {
            "bootstrap-only": {"role": "admin", "port_list": [1]},
        },
        "users": {
            "admin": {
                "role": "console_user",
                "groups": ["bootstrap-only"],
                "password": "must-not-survive",
            },
            "bmc": {
                "role": "admin",
                "groups": ["bootstrap-only", "operators"],
                "password": "must-not-survive",
            },
        },
    }


def make_generator(tables=None):
    return ConsoleServerConfigGenerator(
        config_db=FakeConfigDb(tables or base_tables()),
        local_user_exists=lambda username: username == "admin",
    )


def test_generate_complete_snapshot_preserves_platform_and_overrides_configdb(caplog):
    generator = make_generator()

    with caplog.at_level(logging.WARNING):
        result = generator.generate(bootstrap())

    assert result["listen"] == {"host": "127.0.0.1", "port": 25001}
    assert result["future_top_level"] == {"preserve": True}
    assert result["info"] == {
        "base_port": 35000,
        "no_of_user": 16,
        "no_of_group": 16,
        "no_of_port": 2,
        "platform_marker": "keep",
    }
    assert result["lines"]["1"]["device"] == "/dev/ttyTEST1"
    assert result["lines"]["1"]["baudrate"] == 9600
    assert result["lines"]["1"]["flowcontrol"] == "xonxoff"
    assert result["lines"]["1"]["label"] == "SONIC1"
    assert result["groups"] == {
        "operators": {"role": "operator", "port_list": [1, 2]}
    }
    assert result["users"]["admin"] == {
        "role": "admin",
        "groups": ["operators"],
    }
    assert result["users"]["bmc"] == {
        "role": "admin",
        "groups": ["operators"],
    }
    assert "missing" not in result["users"]
    assert all("password" not in entry for entry in result["users"].values())
    assert "Skipping ConfigDB user missing" in caplog.text
    assert "Preserving unmanaged bootstrap user bmc" in caplog.text


def test_requires_complete_contiguous_port_inventory():
    tables = base_tables()
    del tables["CONSOLE_SERVER_PORT"]["2"]

    with pytest.raises(ConfigGenerationError, match=r"missing port\(s\): 2"):
        ConsoleServerConfigGenerator(
            config_db=FakeConfigDb(tables),
            local_user_exists=lambda username: True,
        ).generate(bootstrap())


def test_requires_matching_bootstrap_line():
    value = bootstrap()
    del value["lines"]["2"]

    with pytest.raises(ConfigGenerationError, match="missing line 2"):
        make_generator().generate(value)


def test_invalid_candidate_does_not_replace_existing_output(tmp_path):
    bootstrap_path = tmp_path / "bootstrap.json"
    output_path = tmp_path / "config.json"
    value = bootstrap()
    value["lines"].pop("2")
    bootstrap_path.write_text(json.dumps(value), encoding="utf-8")
    output_path.write_text('{"old": true}\n', encoding="utf-8")

    with pytest.raises(ConfigGenerationError):
        make_generator().generate_file(
            bootstrap_path=bootstrap_path,
            output_path=output_path,
        )

    assert json.loads(output_path.read_text(encoding="utf-8")) == {"old": True}


def test_atomic_output_is_valid_json_and_mode_0600(tmp_path):
    bootstrap_path = tmp_path / "bootstrap.json"
    output_path = tmp_path / "seriald" / "config.json"
    bootstrap_path.write_text(json.dumps(bootstrap()), encoding="utf-8")

    generated = make_generator().generate_file(
        bootstrap_path=bootstrap_path,
        output_path=output_path,
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == generated
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert list(output_path.parent.glob(".config.json.*.tmp")) == []


def test_invalid_product_info_fails_generation():
    tables = base_tables()
    tables["CONSOLE_SERVER_PRODUCT_INFO"]["global"]["base_port"] = "65535"

    with pytest.raises(ConfigGenerationError, match="TCP port range exceeds 65535"):
        ConsoleServerConfigGenerator(
            config_db=FakeConfigDb(tables),
            local_user_exists=lambda username: True,
        ).generate(bootstrap())
