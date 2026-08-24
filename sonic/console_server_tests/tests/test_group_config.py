from tests.cli_harness import assert_rejected, assert_success
from tests.conftest import require_destructive

GROUP = "pytest-console-group"


def _show(cli):
    result = cli.run("show console-server group", privileged=False)
    assert_success(result)
    return result.stdout


def test_tp_grp_001_create_group(cli_for, backend_mode, allow_destructive):
    cli = cli_for("group_config")
    if backend_mode == "stub":
        assert_success(cli.run("config console-server group add test-group 1-3 --role console_user"))
        assert cli.groups["test-group"] == {"role": "console_user", "ports": [1, 2, 3]}
        return
    require_destructive(backend_mode, allow_destructive)
    cli.run(f"config console-server group delete {GROUP}")
    try:
        assert_success(cli.run(f"config console-server group add {GROUP} 1-3 --role console_user"))
        output = _show(cli)
        assert GROUP in output and "console_user" in output
    finally:
        cli.run(f"config console-server group delete {GROUP}")


def test_tp_grp_002_replace_complete_definition(cli_for, backend_mode, allow_destructive):
    cli = cli_for("group_config")
    name = "test-group" if backend_mode == "stub" else GROUP
    require_destructive(backend_mode, allow_destructive)
    cli.run(f"config console-server group add {name} 1-3 --role console_user")
    try:
        assert_success(cli.run(f"config console-server group add {name} 2,4,6 --role operator"))
        if backend_mode == "stub":
            assert cli.groups[name] == {"role": "operator", "ports": [2, 4, 6]}
        else:
            output = _show(cli)
            line = next(line for line in output.splitlines() if name in line)
            assert "operator" in line
            for port in ("2", "4", "6"):
                assert port in line
    finally:
        cli.run(f"config console-server group delete {name}")


def test_tp_grp_003_all_lines(cli_for, backend_mode, allow_destructive):
    cli = cli_for("group_config")
    name = "all-test-lines" if backend_mode == "stub" else GROUP
    require_destructive(backend_mode, allow_destructive)
    try:
        assert_success(cli.run(f"config console-server group add {name} all"))
        if backend_mode == "stub":
            assert cli.groups[name]["ports"] == list(range(1, 25))
        else:
            assert name in _show(cli)
    finally:
        cli.run(f"config console-server group delete {name}")


def test_tp_grp_004_repeat_definition(cli_for, backend_mode, allow_destructive):
    cli = cli_for("group_config")
    name = "test-group" if backend_mode == "stub" else GROUP
    require_destructive(backend_mode, allow_destructive)
    command = f"config console-server group add {name} 1-3 --role console_user"
    try:
        assert_success(cli.run(command))
        first = _show(cli) if backend_mode == "live" else repr(cli.snapshot())
        assert_success(cli.run(command))
        second = _show(cli) if backend_mode == "live" else repr(cli.snapshot())
        assert first == second
    finally:
        cli.run(f"config console-server group delete {name}")


def test_tp_grp_005_delete_group(cli_for, backend_mode, allow_destructive):
    cli = cli_for("group_config")
    name = "test-group" if backend_mode == "stub" else GROUP
    require_destructive(backend_mode, allow_destructive)
    cli.run(f"config console-server group add {name} 1-3")
    assert_success(cli.run(f"config console-server group delete {name}"))
    if backend_mode == "stub":
        assert name not in cli.groups
    else:
        assert name not in _show(cli)


def test_group_negative_cases(cli_for):
    cli = cli_for("group_config")
    for command in (
        "config console-server group add bad-group 999",
        "config console-server group add bad-group 1-3,,5",
        "config console-server group add bad-group 1 --role observer",
        "config console-server group delete no-such-group",
    ):
        before = _show(cli) if getattr(cli, "is_live", False) else repr(cli.snapshot())
        result = cli.run(command)
        assert_rejected(result)
        after = _show(cli) if getattr(cli, "is_live", False) else repr(cli.snapshot())
        assert before == after
