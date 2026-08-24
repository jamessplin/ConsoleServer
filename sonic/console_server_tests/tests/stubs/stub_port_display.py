from tests.cli_harness import CommandResult


class PortDisplayStub:
    def __init__(self, max_ports: int = 24, base_port: int = 35000):
        self.max_ports = max_ports
        self.base_port = base_port

    def run(self, command: str) -> CommandResult:
        if command == "show console-server product-info":
            return CommandResult(command, stdout=f"Base Port: {self.base_port}\nMax Ports: {self.max_ports}")
        if command == "show console-server port":
            rows = ["Line TCP Port Label Mode Max Clients Idle Timeout Baudrate Databits Stopbits Parity Flowcontrol"]
            for line in range(1, self.max_ports + 1):
                rows.append(f"{line} {self.base_port + line} COM{line} shared 4 600 115200 8 1 none none")
            return CommandResult(command, stdout="\n".join(rows))
        return CommandResult(command, 2, stderr="Unknown command")
