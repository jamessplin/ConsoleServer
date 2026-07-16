from __future__ import annotations

from unittest.mock import call, patch

import pytest

from config import main


def test_restart_console_server_after_load_skips_disabled_service():
    with patch.object(
        main.clicommon,
        "run_command",
        return_value=("", 1),
    ) as run_command:
        main._restart_console_server_after_load()

    run_command.assert_called_once_with(
        [
            "systemctl",
            "is-enabled",
            "--quiet",
            "console-server.service",
        ],
        return_cmd=True,
    )


def test_restart_console_server_after_load_restarts_enabled_service():
    with patch.object(
        main.clicommon,
        "run_command",
        side_effect=[("", 0), ("", 0)],
    ) as run_command:
        main._restart_console_server_after_load()

    assert run_command.call_args_list == [
        call(
            [
                "systemctl",
                "is-enabled",
                "--quiet",
                "console-server.service",
            ],
            return_cmd=True,
        ),
        call(
            [
                "systemctl",
                "restart",
                "console-server.service",
            ],
            display_cmd=True,
        ),
    ]


def test_config_load_restarts_console_server_once_after_success():
    with (
        patch.object(main.multi_asic, "get_num_asics", return_value=1),
        patch.object(main.multi_asic, "is_multi_asic", return_value=False),
        patch.object(main.os.path, "exists", return_value=True),
        patch.object(main.clicommon, "run_command") as run_command,
        patch.object(main, "_restart_console_server_after_load") as restart,
    ):
        main.load.callback("/tmp/config_db.json", True)

    run_command.assert_called_once_with(
        [
            str(main.SONIC_CFGGEN_PATH),
            "-j",
            "/tmp/config_db.json",
            "--write-to-db",
        ],
        display_cmd=True,
    )
    restart.assert_called_once_with()


def test_config_load_does_not_restart_when_file_is_missing():
    with (
        patch.object(main.multi_asic, "get_num_asics", return_value=1),
        patch.object(main.multi_asic, "is_multi_asic", return_value=False),
        patch.object(main.os.path, "exists", return_value=False),
        patch.object(main.clicommon, "run_command") as run_command,
        patch.object(main, "_restart_console_server_after_load") as restart,
    ):
        main.load.callback("/tmp/missing.json", True)

    run_command.assert_not_called()
    restart.assert_not_called()


def test_config_load_does_not_restart_when_cfggen_fails():
    with (
        patch.object(main.multi_asic, "get_num_asics", return_value=1),
        patch.object(main.multi_asic, "is_multi_asic", return_value=False),
        patch.object(main.os.path, "exists", return_value=True),
        patch.object(
            main.clicommon,
            "run_command",
            side_effect=SystemExit(1),
        ),
        patch.object(main, "_restart_console_server_after_load") as restart,
    ):
        with pytest.raises(SystemExit) as error:
            main.load.callback("/tmp/config_db.json", True)

    assert error.value.code == 1
    restart.assert_not_called()
