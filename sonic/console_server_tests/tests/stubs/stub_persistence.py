from copy import deepcopy
from tests.cli_harness import CommandResult


class PersistenceStub:
    def __init__(self):
        self.running = {"label": "COM1", "group": None, "user_role": None}
        self.saved = deepcopy(self.running)
        self.service_running = True

    def run(self, command: str) -> CommandResult:
        if command == "config save -y":
            self.saved = deepcopy(self.running); return CommandResult(command, stdout="Configuration saved")
        if command == "reboot":
            self.running = deepcopy(self.saved); self.service_running = True; return CommandResult(command, stdout="Rebooted")
        if command == "service console-server restart":
            self.service_running = True; return CommandResult(command, stdout="Restarted")
        if command.startswith("config console-server port label 1 "):
            self.running["label"] = command.rsplit(" ", 1)[1]; return CommandResult(command, stdout="Updated")
        if command == "show console-server port":
            return CommandResult(command, stdout=self.running["label"])
        return CommandResult(command, 2, stderr="Unknown command")
