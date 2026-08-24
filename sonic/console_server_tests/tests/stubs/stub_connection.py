from tests.cli_harness import CommandResult


class ConnectionStub:
    def __init__(self):
        self.labels = {1: "TEST-CONSOLE-1"}
        self.mode = "shared"
        self.max_clients = 2
        self.active = []

    def run(self, command: str, *, client: str = "client-1") -> CommandResult:
        parts = command.split()
        if parts[:3] != ["connect", "console-server", parts[2] if len(parts) > 2 else ""] or len(parts) != 4:
            return CommandResult(command, 2, stderr="Invalid connect command")
        selector, value = parts[2], parts[3]
        if selector == "line":
            if value != "1": return CommandResult(command, 2, stderr="Unknown console line")
        elif selector == "label":
            if value != self.labels[1]: return CommandResult(command, 2, stderr="Unknown console label")
        else:
            return CommandResult(command, 2, stderr="Invalid selector")
        if self.mode == "exclusive" and self.active:
            return CommandResult(command, 1, stderr="Console line is already in use")
        if len(self.active) >= self.max_clients:
            return CommandResult(command, 1, stderr="Maximum clients reached")
        self.active.append(client)
        return CommandResult(command, stdout="Connected to line 1")
