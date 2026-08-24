from __future__ import annotations

import pytest

from tests.cli_backend import LiveSonicCli, load_stub


def pytest_addoption(parser):
    group = parser.getgroup("sonic-console-server")
    group.addoption("--backend", choices=("stub", "live"), default="stub",
                    help="Run with local stubs or directly on this SONiC switch")
    group.addoption("--allow-destructive", action="store_true",
                    help="Allow tests that change switch configuration")
    group.addoption("--allow-user-tests", action="store_true",
                    help="Allow tests that create/change/delete Linux users")
    group.addoption("--test-port", type=int, default=1,
                    help="Console line used by live configuration tests")


@pytest.fixture(scope="session")
def backend_mode(pytestconfig):
    return pytestconfig.getoption("--backend")


@pytest.fixture(scope="session")
def live_cli(backend_mode):
    if backend_mode != "live":
        pytest.skip("live backend only")
    return LiveSonicCli()


@pytest.fixture
def cli_for(backend_mode):
    def factory(section: str):
        return LiveSonicCli() if backend_mode == "live" else load_stub(section)
    return factory


@pytest.fixture(scope="session")
def allow_destructive(pytestconfig):
    return pytestconfig.getoption("--allow-destructive")


@pytest.fixture(scope="session")
def allow_user_tests(pytestconfig):
    return pytestconfig.getoption("--allow-user-tests")


@pytest.fixture(scope="session")
def test_port(pytestconfig):
    return pytestconfig.getoption("--test-port")


def require_destructive(backend_mode, allow_destructive):
    if backend_mode == "live" and not allow_destructive:
        pytest.skip("live test changes configuration; add --allow-destructive")


def require_user_tests(backend_mode, allow_destructive, allow_user_tests):
    require_destructive(backend_mode, allow_destructive)
    if backend_mode == "live" and not allow_user_tests:
        pytest.skip("live test changes Linux users; add --allow-user-tests")
