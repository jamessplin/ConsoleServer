import pytest

from tests.cli_harness import assert_rejected, assert_success


def test_tp_ses_001_show_sessions_command(cli_for):
    cli = cli_for("sessions")
    result = cli.run("show console-server sessions", privileged=False)
    assert_success(result)
    assert "Traceback" not in result.combined_output


def test_tp_ses_005_internal_fields_hidden(cli_for):
    cli = cli_for("sessions")
    result = cli.run("show console-server sessions", privileged=False)
    assert_success(result)
    output = result.stdout.lower()
    assert "session_id" not in output
    assert "last_activity" not in output


def test_stub_session_shapes(cli_for, backend_mode):
    if backend_mode == "live":
        pytest.skip("requires controlled live clients")
    cli = cli_for("sessions")
    assert "No active" in cli.run("show console-server sessions").stdout
    cli.add()
    assert len(cli.run("show console-server sessions").stdout.splitlines()) == 1
    cli.add(port=50002)
    assert len(cli.run("show console-server sessions").stdout.splitlines()) == 2
    cli.runtime_available = False
    assert_rejected(cli.run("show console-server sessions"))


@pytest.mark.manual
def test_tp_ses_002_through_007_live_manual():
    pytest.skip("manual: create controlled clients, idle countdown, sorting, and runtime outage")
