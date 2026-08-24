from tests.cli_harness import CommandResult


class ProductInfoStub:
    def __init__(self):
        self.values = {"Base Port": 35000, "Max Ports": 24, "Max Users": 16, "Max Groups": 16}

    def run(self, command: str) -> CommandResult:
        if command != "show console-server product-info":
            return CommandResult(command, 2, stderr="Unknown command")
        body = "\n".join(f"{key}: {value}" for key, value in self.values.items())
        return CommandResult(command, stdout=body)
