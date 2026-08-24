from tests.cli_harness import CommandResult


class SessionsStub:
    def __init__(self):
        self.sessions = []
        self.runtime_available = True

    def add(self, line=1, mode="shared", user="admin", role="writer", ip="10.0.0.1", port=50001, idle=600, left=600):
        self.sessions.append({"line": line, "mode": mode, "user": user, "role": role, "ip": ip, "port": port, "idle": idle, "left": left})

    def tick(self, seconds: int):
        for session in self.sessions:
            session["left"] = max(0, session["left"] - seconds)
        self.sessions = [s for s in self.sessions if s["left"] > 0 or s["idle"] == 0]

    def run(self, command: str) -> CommandResult:
        if command != "show console-server sessions": return CommandResult(command, 2, stderr="Unknown command")
        if not self.runtime_available: return CommandResult(command, 1, stderr="ConsoleServer runtime is unavailable")
        if not self.sessions: return CommandResult(command, stdout="No active console-server sessions.")
        rows = []
        for s in sorted(self.sessions, key=lambda x: (x["line"], x["port"])):
            rows.append(f"{s['line']} {s['mode']} {s['user']} {s['role']} {s['ip']} {s['port']} {s['idle']} {s['left']}")
        return CommandResult(command, stdout="\n".join(rows))
