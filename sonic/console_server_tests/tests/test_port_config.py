import pytest

from tests.cli_harness import assert_success
from tests.conftest import require_destructive
from tests.live_helpers import value_in_port_row


CASES = [
    ("TP-PCFG-001", "baudrate", "9600"),
    ("TP-PCFG-002", "databits", "8"),
    ("TP-PCFG-003", "parity", "none"),
    ("TP-PCFG-004", "stopbits", "1"),
    ("TP-PCFG-005", "flowcontrol", "none"),
    ("TP-PCFG-006", "mode", "shared"),
    ("TP-PCFG-007", "mode", "exclusive"),
    ("TP-PCFG-008", "max-clients", "4"),
    ("TP-PCFG-009", "idle-timeout", "600"),
    ("TP-PCFG-010", "idle-timeout", "0"),
    ("TP-PCFG-011", "label", "TEST-CONSOLE-1"),
]


@pytest.mark.parametrize("test_id,field,value", CASES)
def test_port_configuration(test_id, field, value, cli_for, backend_mode,
                            allow_destructive, test_port):
    cli = cli_for("port_config")
    if backend_mode == "stub":
        before = cli.snapshot()[1]
        result = cli.run(f"config console-server port {field} 1 {value}")
        assert_success(result)
        assert cli.ports[1][field] == value
        for other_field, old_value in before.items():
            if other_field != field:
                assert cli.ports[1][other_field] == old_value
        return

    require_destructive(backend_mode, allow_destructive)
    result = cli.run(f"config console-server port {field} {test_port} {value}")
    assert_success(result)
    shown = cli.run("show console-server port", privileged=False)
    assert_success(shown)
    assert value_in_port_row(shown.stdout, test_port, value)


def test_tp_pcfg_012_no_op_update(cli_for, backend_mode, allow_destructive,
                                  test_port):
    cli = cli_for("port_config")
    if backend_mode == "stub":
        result = cli.run("config console-server port baudrate 1 115200")
        assert_success(result)
        assert result.stdout == "No change"
        assert cli.runtime_updates == 0
        assert cli.persistent_updates == 0
        return

    require_destructive(backend_mode, allow_destructive)
    shown = cli.run("show console-server port", privileged=False)
    assert_success(shown)
    row = next(line.split() for line in shown.stdout.splitlines()
               if line.split() and line.split()[0] == str(test_port))
    baudrate = row[6]
    first = cli.run(f"config console-server port baudrate {test_port} {baudrate}")
    second = cli.run(f"config console-server port baudrate {test_port} {baudrate}")
    assert_success(first)
    assert_success(second)
