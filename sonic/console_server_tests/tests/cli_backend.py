from __future__ import annotations

import os
import shlex
import subprocess
import inspect
from dataclasses import dataclass
from typing import Any

from tests.cli_harness import CommandResult


class LiveSonicCli:
    """Execute public SONiC CLI commands on the local switch."""

    is_live = True

    def run(self, command: str, privileged: bool = True, **_: Any) -> CommandResult:
        argv = shlex.split(command)
        if privileged and argv and argv[0] in {"config", "systemctl", "service", "reboot"}:
            if os.geteuid() != 0:
                argv = ["sudo", "-n", *argv]
        completed = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=int(os.environ.get("SONIC_CLI_TEST_TIMEOUT", "30")),
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class StubAdapter:
    """Normalize old section stubs to the common live backend interface."""

    is_live = False

    def __init__(self, stub):
        object.__setattr__(self, "_stub", stub)

    def __getattr__(self, name):
        return getattr(self._stub, name)

    def __setattr__(self, name, value):
        if name == "_stub":
            object.__setattr__(self, name, value)
        else:
            setattr(self._stub, name, value)

    def run(self, command: str, **kwargs):
        signature = inspect.signature(self._stub.run)
        accepted = {k: v for k, v in kwargs.items() if k in signature.parameters}
        return self._stub.run(command, **accepted)


def load_stub(section: str):
    module = __import__(f"tests.stubs.stub_{section}", fromlist=["*"])
    expected = "".join(part.title() for part in section.split("_")) + "Stub"
    return StubAdapter(getattr(module, expected)())
