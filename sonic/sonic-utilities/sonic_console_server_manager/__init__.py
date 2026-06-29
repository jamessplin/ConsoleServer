"""SONiC integration helpers for the generic ConsoleServer component."""

from .manager import (
    ConfigDbOperation,
    SonicConsoleServerManager,
    build_port_config,
    local_user_exists,
    normalize_group_ports,
    normalize_port_label,
    parse_port_expression,
    validate_local_user_exists,
    validate_ports,
    validate_reserved_port_label,
    validate_unique_label,
)

__all__ = [
    "ConfigDbOperation",
    "SonicConsoleServerManager",
    "build_port_config",
    "local_user_exists",
    "normalize_group_ports",
    "normalize_port_label",
    "parse_port_expression",
    "validate_local_user_exists",
    "validate_ports",
    "validate_reserved_port_label",
    "validate_unique_label",
]
