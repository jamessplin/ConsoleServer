import pytest

from tests.cli_harness import assert_success
from tests.conftest import require_destructive


def test_tp_pers_001_config_save(cli_for, backend_mode, allow_destructive):
    cli = cli_for("persistence")
    if backend_mode == "stub":
        cli.run("config console-server port label 1 TEST-CONSOLE-1")
        assert_success(cli.run("config save -y"))
        assert cli.saved["label"] == "TEST-CONSOLE-1"
        return
    require_destructive(backend_mode, allow_destructive)
    result = cli.run("config save -y")
    assert_success(result)


def test_tp_pers_003_service_restart(cli_for, backend_mode, allow_destructive):
    if backend_mode == "stub":
        cli = cli_for("persistence")
        cli.run("config console-server port label 1 TEST-CONSOLE-1")
        assert_success(cli.run("service console-server restart"))
        assert cli.service_running
        return
    pytest.skip("live service restart is intentionally manual; it interrupts active console sessions")


@pytest.mark.manual
def test_tp_pers_002_and_004_reboot_manual():
    pytest.skip("manual: save/reboot and unsaved-change behavior require reboot coordination")
