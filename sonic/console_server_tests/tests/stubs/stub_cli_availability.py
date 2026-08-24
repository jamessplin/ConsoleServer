from tests.cli_harness import CommandResult


class CliAvailabilityStub:
    def run(self, command: str, *, privileged: bool = True) -> CommandResult:
        help_map = {
            "config --help": "Commands:\n  console-server",
            "show --help": "Commands:\n  console-server",
            "connect --help": "Commands:\n  console-server",
            "config console-server --help": "Commands:\n  port\n  group\n  user",
            "show console-server --help": "Commands:\n  port\n  group\n  user\n  sessions\n  product-info",
            "connect console-server --help": "Commands:\n  line\n  label",
        }
        if command in help_map:
            return CommandResult(command, stdout=help_map[command])
        if command.startswith("config console-server") and not privileged:
            return CommandResult(command, 1, stderr="Administrator privilege is required")
        return CommandResult(command, 2, stderr="Unknown command")
