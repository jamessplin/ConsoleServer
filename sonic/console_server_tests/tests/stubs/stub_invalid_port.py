from copy import deepcopy
from tests.cli_harness import CommandResult


class InvalidPortStub:
    def __init__(self):
        self.ports = {1: {"baudrate": "115200", "parity": "none", "mode": "shared", "idle-timeout": "600", "label": "COM1"}, 2: {"label": "COM2"}}

    def snapshot(self):
        return deepcopy(self.ports)

    def run(self, command: str) -> CommandResult:
        tokens = command.split()
        if len(tokens) != 6:
            return CommandResult(command, 2, stderr="Invalid usage")
        field, line_s, value = tokens[3], tokens[4], tokens[5]
        try:
            line = int(line_s)
        except ValueError:
            return CommandResult(command, 2, stderr="Invalid line")
        if line < 1 or line > 24:
            return CommandResult(command, 2, stderr="Console line is outside the supported range")
        if field == "baudrate" and value not in {"9600", "19200", "38400", "57600", "115200"}:
            return CommandResult(command, 2, stderr="Unsupported baud rate")
        if field == "parity" and value not in {"none", "odd", "even"}:
            return CommandResult(command, 2, stderr="Invalid parity")
        if field == "mode" and value not in {"shared", "exclusive"}:
            return CommandResult(command, 2, stderr="Invalid access mode")
        if field == "idle-timeout" and int(value) > 86400:
            return CommandResult(command, 2, stderr="Idle timeout is above the limit")
        if field == "label":
            if value in {p.get("label") for n, p in self.ports.items() if n != line}:
                return CommandResult(command, 2, stderr="Duplicate label")
            if value.startswith("COM") and value[3:].isdigit() and int(value[3:]) != line:
                return CommandResult(command, 2, stderr="Reserved default label belongs to another line")
        return CommandResult(command, stdout="Updated")
