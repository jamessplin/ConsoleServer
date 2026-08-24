from tests.cli_harness import assert_success
from tests.live_helpers import find_port_row


def _rows(output: str):
    return [line.split() for line in output.splitlines() if line.split() and line.split()[0].isdigit()]


def test_tp_port_001_show_all_console_lines(cli_for):
    cli = cli_for("port_display")
    result = cli.run("show console-server port", privileged=False)
    assert_success(result)
    rows = _rows(result.stdout)
    assert rows
    numbers = [int(row[0]) for row in rows]
    assert numbers == sorted(numbers)
    assert len(numbers) == len(set(numbers))


def test_tp_port_002_tcp_port_sequence(cli_for):
    cli = cli_for("port_display")
    result = cli.run("show console-server port", privileged=False)
    assert_success(result)
    rows = _rows(result.stdout)
    base = int(rows[0][1]) - int(rows[0][0])
    for row in rows:
        assert int(row[1]) == base + int(row[0])


def test_tp_port_003_labels_are_unique(cli_for):
    cli = cli_for("port_display")
    result = cli.run("show console-server port", privileged=False)
    assert_success(result)
    rows = _rows(result.stdout)
    labels = [row[2] for row in rows]
    assert len(labels) == len(set(labels))
