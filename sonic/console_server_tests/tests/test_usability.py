from concurrent.futures import ThreadPoolExecutor

from tests.cli_harness import assert_rejected, assert_success


def test_tp_use_001_repeated_show_commands(cli_for):
    cli = cli_for("usability")
    commands = (
        "show console-server port",
        "show console-server group",
        "show console-server user",
        "show console-server sessions",
        "show console-server product-info",
    )
    for command in commands:
        results = [cli.run(command, privileged=False) for _ in range(10)]
        for result in results:
            assert_success(result)
            assert "Traceback" not in result.combined_output


def test_tp_use_002_concurrent_session_display(cli_for):
    cli = cli_for("usability")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: cli.run("show console-server sessions", privileged=False), range(8)))
    for result in results:
        assert_success(result)


def test_tp_use_004_clear_errors(cli_for):
    cli = cli_for("usability")
    result = cli.run("config console-server invalid")
    assert_rejected(result)
    assert "Traceback" not in result.combined_output
