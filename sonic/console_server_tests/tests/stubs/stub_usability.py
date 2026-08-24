from tests.cli_harness import CommandResult


class UsabilityStub:
    def __init__(self):
        self.sessions = 0

    def run(self, command: str) -> CommandResult:
        valid = {
            "show console-server port": "ports",
            "show console-server group": "groups",
            "show console-server user": "users",
            "show console-server sessions": f"sessions={self.sessions}",
            "show console-server product-info": "product-info",
        }
        if command in valid: return CommandResult(command, stdout=valid[command])
        return CommandResult(command, 2, stderr="Clear user-facing error")
