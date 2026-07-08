"""Show commands for SONiC console-server configuration and runtime state."""

from __future__ import annotations

from typing import Any, Iterable

import click
from tabulate import tabulate

from sonic_console_server_manager.manager import (
    ConsoleServerManagerError,
    create_default_manager,
)


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help", "-?"]}
_MISSING = "-"


def _display_value(value: Any) -> Any:
    if value is None or value == "":
        return _MISSING
    return value


def _display_list(values: Iterable[Any]) -> str:
    rendered = ",".join(str(value) for value in values)
    return rendered or _MISSING


def _echo_table(rows: list[list[Any]], headers: list[str], empty_message: str) -> None:
    if not rows:
        click.echo(empty_message)
        return
    click.echo(tabulate(rows, headers=headers, tablefmt="simple", disable_numparse=True))


@click.group(
    name="console-server",
    context_settings=CONTEXT_SETTINGS,
)
def console_server() -> None:
    """Show console-server configuration and runtime state."""


@console_server.command("port")
def port() -> None:
    """Show configured console ports."""

    try:
        manager = create_default_manager()
        records = manager.get_port_configs()
        product_info = manager.get_product_info()
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    base_port = product_info["base_port"]
    fields = [
        "label",
        "mode",
        "max_clients",
        "idle_timeout",
        "baudrate",
        "databits",
        "stopbits",
        "parity",
        "flowcontrol",
    ]
    rows = [
        [
            _display_value(record.get("port")),
            _display_value(base_port + int(record["port"])),
        ]
        + [_display_value(record.get(field)) for field in fields]
        for record in records
    ]
    _echo_table(
        rows,
        [
            "Line",
            "TCP Port",
            "Label",
            "Mode",
            "Max Clients",
            "Idle Timeout",
            "Baudrate",
            "Databits",
            "Stopbits",
            "Parity",
            "Flowcontrol",
        ],
        "No console-server ports configured.",
    )


@console_server.command("user")
def user() -> None:
    """Show configured console-server users."""

    try:
        records = create_default_manager().get_user_configs()
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    rows = [
        [
            _display_value(record.get("username")),
            _display_value(record.get("role")),
            _display_list(record.get("groups", [])),
        ]
        for record in records
    ]
    _echo_table(
        rows,
        ["Username", "Role", "Groups"],
        "No console-server users configured.",
    )


@console_server.command("group")
def group() -> None:
    """Show configured console-server groups."""

    try:
        records = create_default_manager().get_group_configs()
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    rows = [
        [
            _display_value(record.get("group")),
            _display_value(record.get("role")),
            _display_list(record.get("ports", [])),
        ]
        for record in records
    ]
    _echo_table(
        rows,
        ["Group", "Role", "Ports"],
        "No console-server groups configured.",
    )

@console_server.command("product-info")
def product_info() -> None:
    """Show console-server product configuration and limits."""

    try:
        info = create_default_manager().get_product_info()
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    click.echo("Product Configuration & Limits")
    click.echo("------------------------------")
    click.echo(f"Base Port  : {info['base_port']}")
    click.echo(f"Max Ports  : {info['max_ports']}")
    click.echo(f"Max Users  : {info['max_users']}")
    click.echo(f"Max Groups : {info['max_groups']}")


@console_server.command("sessions")
def sessions() -> None:
    """Show active console-server sessions. Times are displayed in seconds."""

    try:
        records = create_default_manager().get_sessions()
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    rows = [
        [
            _display_value(record.get("line")),
            _display_value(record.get("mode")),
            _display_value(record.get("user")),
            _display_value(record.get("role")),
            _display_value(record.get("ip")),
            _display_value(record.get("port")),
            _display_value(record.get("idle_timeout")),
            _display_value(record.get("time_left")),
        ]
        for record in records
    ]
    _echo_table(
        rows,
        [
            "Line",
            "Mode",
            "User",
            "Role",
            "Client IP",
            "Client Port",
            "Idle Timeout",
            "Time Left",
        ],
        "No active console-server sessions.",
    )

