"""SONiC integration helpers for the generic ConsoleServer component."""

from .manager import (
    CommandResult,
    ConfigDbOperation,
    ConsoleServerManagerError,
    SonicConsoleServerManager,
    build_port_config,
    create_default_manager,
    normalize_group_ports,
    normalize_port_label,
    normalize_username,
    parse_port_expression,
    validate_password,
    validate_ports,
    validate_reserved_port_label,
    validate_unique_label,
)

__all__ = [
    "CommandResult",
    "ConfigDbOperation",
    "ConsoleServerManagerError",
    "SonicConsoleServerManager",
    "build_port_config",
    "create_default_manager",
    "normalize_group_ports",
    "normalize_port_label",
    "normalize_username",
    "parse_port_expression",
    "validate_password",
    "validate_ports",
    "validate_reserved_port_label",
    "validate_unique_label",
]
