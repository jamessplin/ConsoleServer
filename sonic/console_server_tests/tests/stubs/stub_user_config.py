from copy import deepcopy
from tests.cli_harness import CommandResult


class UserConfigStub:
    def __init__(self):
        self.groups = {"all-test-lines"}
        self.users = {}

    def snapshot(self):
        return deepcopy(self.users)

    def run(self, command: str, *, prompted_password: str | None = None) -> CommandResult:
        if command == "show console-server user":
            rows = [f"{name} {u['role']} {','.join(u['groups'])}" for name, u in sorted(self.users.items())]
            return CommandResult(command, stdout="\n".join(rows))
        parts = command.split()
        if parts[:4] == ["config", "console-server", "user", "add"]:
            name = parts[4]
            if "--password" in parts and "--prompt-password" in parts:
                return CommandResult(command, 2, stderr="Password options are mutually exclusive")
            role = parts[parts.index("--role") + 1] if "--role" in parts else None
            if role is not None and role not in {"none", "admin", "console_user", "operator"}:
                return CommandResult(command, 2, stderr="Invalid role")
            groups = parts[parts.index("--groups") + 1].split(",") if "--groups" in parts else None
            if groups and any(g not in self.groups for g in groups):
                return CommandResult(command, 2, stderr="Unknown group")
            current = self.users.get(name, {"role": "none", "groups": [], "password": None})
            self.users[name] = {
                "role": current["role"] if role is None else role,
                "groups": current["groups"] if groups is None else groups,
                "password": prompted_password if "--prompt-password" in parts else current["password"],
            }
            return CommandResult(command, stdout="Updated")
        if parts[:4] == ["config", "console-server", "user", "password"]:
            name = parts[4]
            if name not in self.users:
                return CommandResult(command, 2, stderr="User does not exist")
            if "--password" not in parts and "--prompt-password" not in parts:
                return CommandResult(command, 2, stderr="Password option is required")
            self.users[name]["password"] = prompted_password or parts[parts.index("--password") + 1]
            return CommandResult(command, stdout="Password updated")
        if parts[:4] == ["config", "console-server", "user", "delete"]:
            name = parts[4]
            if name not in self.users:
                return CommandResult(command, 2, stderr="User does not exist")
            del self.users[name]
            return CommandResult(command, stdout="Deleted")
        return CommandResult(command, 2, stderr="Invalid command")
