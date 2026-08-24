from tests.cli_harness import assert_rejected, assert_success


def test_tp_cli_001_root_commands(cli_for):
    cli = cli_for("cli_availability")
    for command in ("config --help", "show --help", "connect --help"):
        result = cli.run(command, privileged=False)
        assert_success(result)
        assert "console-server" in result.stdout


def test_tp_cli_002_nested_help(cli_for):
    cli = cli_for("cli_availability")
    for command in (
        "config console-server --help",
        "show console-server --help",
        "connect console-server --help",
    ):
        result = cli.run(command, privileged=False)
        assert_success(result)
        assert "console-server" in result.stdout.lower() or "commands" in result.stdout.lower()


def test_tp_cli_003_configuration_privilege(cli_for, backend_mode):
    if backend_mode == "live":
        # Run explicitly without sudo. Root sessions cannot prove this behavior.
        import os, pytest
        if os.geteuid() == 0:
            pytest.skip("cannot verify non-root rejection from a root test session")
    cli = cli_for("cli_availability")
    result = cli.run("config console-server port baudrate 1 9600", privileged=False)
    assert_rejected(result)
