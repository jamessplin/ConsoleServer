"""Interactive connect commands for the enhanced console-server service."""

from __future__ import annotations

import click

from sonic_console_server_manager.manager import (
    ConsoleServerManagerError,
    create_default_manager,
)


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help", "-?"]}


def _exit_on_failure(exit_status: int) -> None:
    if exit_status:
        raise click.exceptions.Exit(exit_status)


@click.group(
    name="console-server",
    context_settings=CONTEXT_SETTINGS,
)
def console_server() -> None:
    """Connect through the enhanced console-server service."""


@console_server.command(name="line")
@click.argument("port_number", type=int)
def line(port_number: int) -> None:
    """Connect to console-server line PORT_NUMBER."""

    try:
        exit_status = create_default_manager().connect_line(port_number)
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    _exit_on_failure(exit_status)


@console_server.command(name="label")
@click.argument("port_label", metavar="LABEL")
def label(port_label: str) -> None:
    """Connect to the console-server line identified by LABEL."""

    try:
        manager = create_default_manager()
        port_number = manager.resolve_port_by_label(port_label)
        exit_status = manager.connect_line(port_number)
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error

    _exit_on_failure(exit_status)
