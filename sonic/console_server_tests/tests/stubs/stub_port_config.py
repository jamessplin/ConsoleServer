from copy import deepcopy
from tests.cli_harness import CommandResult


class PortConfigStub:
    def __init__(self):
        self.ports = {1: {"baudrate": "115200", "databits": "8", "parity": "none", "stopbits": "1", "flowcontrol": "none", "mode": "shared", "max-clients": "4", "idle-timeout": "600", "label": "COM1"}}
        self.runtime_updates = 0
        self.persistent_updates = 0

    def snapshot(self):
        return deepcopy(self.ports)

    def run(self, command: str) -> CommandResult:
        if command == "show console-server port":
            p = self.ports[1]
            return CommandResult(command, stdout=" ".join(f"{k}={v}" for k, v in p.items()))
        parts = command.split()
        if parts[:4] != ["config", "console-server", "port", parts[3] if len(parts) > 3 else ""] or len(parts) != 6:
            return CommandResult(command, 2, stderr="Invalid command")
        field, line_s, value = parts[3], parts[4], parts[5]
        if int(line_s) != 1 or field not in self.ports[1]:
            return CommandResult(command, 2, stderr="Invalid port or field")
        if self.ports[1][field] == value:
            return CommandResult(command, stdout="No change")
        self.ports[1][field] = value
        self.runtime_updates += 1
        self.persistent_updates += 1
        return CommandResult(command, stdout="Updated")
