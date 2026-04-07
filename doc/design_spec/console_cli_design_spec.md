# Console CLI Design Specification

## Overview
The Console CLI is a Python-based command-line interface for managing serial console sessions, user roles, and device interactions. It is built using the Click library for command parsing and supports both interactive REPL and direct command execution modes.

## Features
- Role-based access control (ADMIN, CONSOLE_USER, OPERATOR, OBSERVER)
- Session management for serial lines
- Policy engine for write access and overrides
- Integration with seriald backend (real or mock)
- Interactive REPL mode and standard CLI mode
- Extensible command structure using Click

## Architecture
- **Entry Point**: `console_cli.py` can be run directly or installed as a system command.
- **Click Group**: The root command group (`cli`) manages subcommands and context.
- **Session/Role Management**: User and role are determined at startup and stored in the Click context (`ctx.obj`).
- **Subcommands**: Each CLI command (e.g., `sd`, `open_line`, `override`, `show_sessions`, `show_config`, `shell`, `exit`) is implemented as a Click subcommand.
- **REPL Mode**: If run with no arguments, an interactive REPL is started, allowing users to enter commands in a loop.
- **Direct Mode**: If run with arguments, the CLI parses and executes the command directly.

## Key Components
- **UserRole**: Enum for user roles.
- **Session**: Represents a user session, including permissions and state.
- **SessionManager**: Manages all sessions and line attachments.
- **PolicyEngine**: Controls write access and overrides for serial lines.
- **FakeSerialDevice/MockSer2Net**: Mock backend for simulating serial device interactions.
- **RoleAwareGroup**: Custom Click group for role-based command filtering in help output.

## Role-Based Access
- Commands can be decorated or tagged with a minimum required role.
- The help system and command execution logic check the user's role before displaying or executing commands.

## Context Passing
- User and role are determined once per process and stored in `ctx.obj` for all subcommands.
- Subcommands access session, manager, and other objects via `ctx.obj`.

## Subprocess Handling
- When launching subprocesses, user/role are not automatically passed; if needed, they should be passed via environment variables or command-line arguments.

## Example Usage
- `console-cli` (starts REPL)
- `console-cli open_line 1` (opens line 1 directly)
- `console-cli show_sessions` (shows all sessions)

## Extensibility
- New commands can be added as Click subcommands.
- Role requirements can be set per command.
- Backend integration can be swapped by replacing the serial device and manager classes.

## Security Considerations
- Role checks are enforced for sensitive commands.
- Only users with sufficient roles can perform write or override actions.

## Error Handling
- Errors in command parsing or execution are caught and displayed to the user.
- REPL mode handles exceptions gracefully and continues the session.

---

This document provides a high-level design for the Console CLI. For implementation details, see the source code in `console_cli.py`.
