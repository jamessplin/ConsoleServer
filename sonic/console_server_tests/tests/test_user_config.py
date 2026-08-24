import os
import pytest

from tests.cli_harness import assert_rejected, assert_success
from tests.conftest import require_user_tests

USER = os.environ.get("SONIC_CLI_TEST_USER", "cs_pytest_user")
PASSWORD = os.environ.get("SONIC_CLI_TEST_PASSWORD")
GROUP = os.environ.get("SONIC_CLI_TEST_GROUP", "all-test-lines")


def _create_stub(cli):
    result = cli.run("config console-server user add cs_test1 --role operator --groups all-test-lines --prompt-password", prompted_password="Secret-1")
    assert_success(result)


def _show(cli):
    result = cli.run("show console-server user", privileged=False)
    assert_success(result)
    return result.stdout


def test_user_commands_stub_suite(cli_for, backend_mode):
    if backend_mode == "live":
        pytest.skip("covered by guarded live lifecycle test")
    cli = cli_for("user_config")
    _create_stub(cli)
    assert "Secret-1" not in _show(cli)
    cli.run("config console-server user add cs_test1 --role admin")
    assert cli.users["cs_test1"]["groups"] == ["all-test-lines"]
    cli.run("config console-server user add cs_test1 --groups all-test-lines")
    before = {k: v for k, v in cli.users["cs_test1"].items() if k != "password"}
    assert_success(cli.run("config console-server user password cs_test1 --prompt-password", prompted_password="Secret-2"))
    assert {k: v for k, v in cli.users["cs_test1"].items() if k != "password"} == before
    assert_success(cli.run("config console-server user delete cs_test1"))


def test_user_live_lifecycle(cli_for, backend_mode, allow_destructive, allow_user_tests):
    if backend_mode != "live":
        pytest.skip("live backend only")
    require_user_tests(backend_mode, allow_destructive, allow_user_tests)
    if not PASSWORD:
        pytest.skip("set SONIC_CLI_TEST_PASSWORD for guarded live user tests")
    cli = cli_for("user_config")
    cli.run(f"config console-server user delete {USER}")
    try:
        result = cli.run(
            f"config console-server user add {USER} --role operator --groups {GROUP} --password {PASSWORD}"
        )
        assert_success(result)
        output = _show(cli)
        assert USER in output and "operator" in output and PASSWORD not in output
        assert_success(cli.run(f"config console-server user add {USER} --role admin"))
        output = _show(cli)
        assert USER in output and "admin" in output
    finally:
        cli.run(f"config console-server user delete {USER}")


def test_user_negative_cases_preserve_visible_state(cli_for, backend_mode):
    cli = cli_for("user_config")
    if backend_mode == "stub":
        _create_stub(cli)
    before = _show(cli)
    commands = (
        f"config console-server user add {USER} --password x --prompt-password",
        f"config console-server user add {USER} --groups no-such-group",
        f"config console-server user password {USER}",
        f"config console-server user add {USER} --role observer",
    )
    for command in commands:
        result = cli.run(command)
        assert_rejected(result)
        assert _show(cli) == before
