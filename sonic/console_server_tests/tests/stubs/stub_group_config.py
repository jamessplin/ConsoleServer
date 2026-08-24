from copy import deepcopy
from tests.cli_harness import CommandResult


class GroupConfigStub:
    def __init__(self):
        self.max_ports = 24
        self.groups = {}

    def snapshot(self):
        return deepcopy(self.groups)

    def _parse_ports(self, expr: str):
        if expr == "all":
            return list(range(1, self.max_ports + 1))
        if ",," in expr:
            raise ValueError("Malformed port list")
        ports = set()
        for token in expr.split(","):
            if "-" in token:
                start, end = map(int, token.split("-"))
                ports.update(range(start, end + 1))
            else:
                ports.add(int(token))
        if not ports or min(ports) < 1 or max(ports) > self.max_ports:
            raise ValueError("Unknown console line")
        return sorted(ports)

    def run(self, command: str) -> CommandResult:
        if command == "show console-server group":
            rows = [f"{name} {data['role']} {','.join(map(str, data['ports']))}" for name, data in sorted(self.groups.items())]
            return CommandResult(command, stdout="\n".join(rows))
        parts = command.split()
        if parts[:4] == ["config", "console-server", "group", "add"]:
            name, expr = parts[4], parts[5]
            role = "console_user"
            if "--role" in parts:
                role = parts[parts.index("--role") + 1]
            if role not in {"admin", "console_user", "operator"}:
                return CommandResult(command, 2, stderr="Unsupported role")
            try:
                ports = self._parse_ports(expr)
            except (ValueError, TypeError) as exc:
                return CommandResult(command, 2, stderr=str(exc))
            self.groups[name] = {"role": role, "ports": ports}
            return CommandResult(command, stdout="Updated")
        if parts[:4] == ["config", "console-server", "group", "delete"]:
            name = parts[4]
            if name not in self.groups:
                return CommandResult(command, 2, stderr="Group does not exist")
            del self.groups[name]
            return CommandResult(command, stdout="Deleted")
        return CommandResult(command, 2, stderr="Invalid command")
