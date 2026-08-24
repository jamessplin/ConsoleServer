import pytest

from tests.cli_harness import assert_rejected, assert_success


def test_connect_negative_cases(cli_for):
    cli = cli_for("connection")
    for command in (
        "connect console-server line 999",
        "connect console-server label NO-SUCH-LABEL",
        "connect console-server label test-console-1",
    ):
        assert_rejected(cli.run(command, privileged=False))


def test_stub_connection_behavior(cli_for, backend_mode):
    if backend_mode == "live":
        pytest.skip("interactive connection requires a terminal and attached serial target")
    cli = cli_for("connection")
    result = cli.run("connect console-server line 1")
    assert_success(result)
    assert "line 1" in result.stdout
    cli = cli_for("connection")
    assert_success(cli.run("connect console-server label TEST-CONSOLE-1"))
    cli = cli_for("connection")
    assert_success(cli.run("connect console-server line 1", client="a"))
    assert_success(cli.run("connect console-server line 1", client="b"))
    assert_rejected(cli.run("connect console-server line 1", client="c"))


@pytest.mark.manual
def test_tp_conn_001_through_005_live_manual():
    pytest.skip("manual: interactive I/O, escape handling, shared/exclusive clients, and client limits")
