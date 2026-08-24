from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


def assert_success(result: CommandResult) -> None:
    assert result.returncode == 0, result.combined_output
    assert "Traceback (most recent call last)" not in result.combined_output


def assert_rejected(result: CommandResult) -> None:
    assert result.returncode != 0
    assert result.combined_output.strip()
    assert "Traceback (most recent call last)" not in result.combined_output
