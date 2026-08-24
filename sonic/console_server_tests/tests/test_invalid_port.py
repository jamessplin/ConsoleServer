import pytest
from tests.cli_harness import assert_rejected, assert_success
from tests.live_helpers import normalized


@pytest.mark.parametrize("command", [
    "config console-server port baudrate 0 9600",
    "config console-server port baudrate 999 9600",
    "config console-server port baudrate 1 12345",
    "config console-server port parity 1 invalid",
    "config console-server port mode 1 invalid",
    "config console-server port idle-timeout 1 86401",
])
def test_invalid_port_inputs_do_not_change_visible_state(command, cli_for):
    cli = cli_for("invalid_port")
    before = cli.run("show console-server port", privileged=False)
    if before.returncode != 0 and not getattr(cli, "is_live", False):
        before_text = repr(cli.snapshot())
    else:
        assert_success(before)
        before_text = normalized(before.stdout)
    result = cli.run(command)
    assert_rejected(result)
    after = cli.run("show console-server port", privileged=False)
    if after.returncode != 0 and not getattr(cli, "is_live", False):
        after_text = repr(cli.snapshot())
    else:
        assert_success(after)
        after_text = normalized(after.stdout)
    assert after_text == before_text
