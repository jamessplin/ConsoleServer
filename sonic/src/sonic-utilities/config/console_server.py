from __future__ import annotations

import click

from sonic_console_server_manager.manager import (
    ConsoleServerManagerError,
    create_default_manager,
)


@click.group(name="console-server")
def console_server() -> None:
    """Configure console-server settings."""


@console_server.group(name="port")
def port() -> None:
    """Configure a physical console port."""


def _set_port_config(port_number: int, field: str, value) -> None:
    try:
        manager = create_default_manager()
        manager.set_port_config(port_number, {field: value})
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error


@port.command(name="baudrate")
@click.argument("port_number", type=int)
@click.argument("rate", type=int)
def baudrate(port_number: int, rate: int) -> None:
    """Set a console port baud rate."""

    _set_port_config(port_number, "baudrate", rate)


@port.command(name="databits")
@click.argument("port_number", type=int)
@click.argument("bits", type=int)
def databits(port_number: int, bits: int) -> None:
    """Set a console port data-bit count."""

    _set_port_config(port_number, "databits", bits)


@port.command(name="parity")
@click.argument("port_number", type=int)
@click.argument("parity_value", metavar="PARITY")
def parity(port_number: int, parity_value: str) -> None:
    """Set a console port parity mode."""

    _set_port_config(port_number, "parity", parity_value)


@port.command(name="stopbits")
@click.argument("port_number", type=int)
@click.argument("bits", type=int)
def stopbits(port_number: int, bits: int) -> None:
    """Set a console port stop-bit count."""

    _set_port_config(port_number, "stopbits", bits)


@port.command(name="flowcontrol")
@click.argument("port_number", type=int)
@click.argument("mode")
def flowcontrol(port_number: int, mode: str) -> None:
    """Set a console port flow-control mode."""

    _set_port_config(port_number, "flowcontrol", mode)


@port.command(name="mode")
@click.argument("port_number", type=int)
@click.argument("mode_value", metavar="MODE")
def mode(port_number: int, mode_value: str) -> None:
    """Set a console port access mode."""

    _set_port_config(port_number, "mode", mode_value)


@port.command(name="max-clients")
@click.argument("port_number", type=int)
@click.argument("count", type=int)
def max_clients(port_number: int, count: int) -> None:
    """Set the maximum number of clients for a console port."""

    _set_port_config(port_number, "max_clients", count)


@port.command(name="idle-timeout")
@click.argument("port_number", type=int)
@click.argument("seconds", type=int)
def idle_timeout(port_number: int, seconds: int) -> None:
    """Set the console port idle timeout in seconds."""

    _set_port_config(port_number, "idle_timeout", seconds)


@port.command(name="label")
@click.argument("port_number", type=int)
@click.argument("label_value", metavar="LABEL")
def label(port_number: int, label_value: str) -> None:
    """Set a console port label."""

    _set_port_config(port_number, "label", label_value)

@console_server.group(name="group")
def group() -> None:
    """Configure console-server groups."""


@group.command(name="add")
@click.argument("group_name")
@click.argument("port_list", metavar="PORT_LIST")
@click.option(
    "--role",
    type=click.Choice(
        ["admin", "console_user", "operator"],
        case_sensitive=False,
    ),
    default="console_user",
    show_default=True,
)
def group_add(
    group_name: str,
    port_list: str,
    role: str,
) -> None:
    """Create a group or update its role and required port membership."""

    try:
        manager = create_default_manager()
        manager.set_group_config(
            group_name,
            role=role,
            ports=port_list,
        )
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error


@group.command(name="delete")
@click.argument("group_name")
def group_delete(group_name: str) -> None:
    """Delete a console-server group."""

    try:
        manager = create_default_manager()
        manager.delete_group(group_name)
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error
@console_server.group(name="user")
def user() -> None:
    """Configure console-server users."""


def _parse_groups(value: str | None) -> list[str] | None:
    if value is None:
        return None

    groups = [item.strip() for item in value.split(",")]
    if not groups or any(not item for item in groups):
        raise click.ClickException(
            "GROUP_LIST must be a comma-separated list of non-empty names"
        )
    return groups


def _prompt_password() -> str:
    return click.prompt(
        "Password",
        hide_input=True,
        confirmation_prompt=True,
        type=str,
    )


def _resolve_password(
    password: str | None,
    prompt_password: bool,
    *,
    required: bool,
) -> str | None:
    if password is not None and prompt_password:
        raise click.ClickException(
            "--password and --prompt-password cannot be used together"
        )

    if prompt_password:
        return _prompt_password()

    if required and password is None:
        raise click.ClickException(
            "Either --password or --prompt-password is required"
        )

    return password


@user.command(name="add")
@click.argument("username")
@click.option(
    "--role",
    type=click.Choice(
        ["none", "admin", "console_user", "operator"],
        case_sensitive=False,
    ),
    default=None,
    help=(
        "User role. Existing role is preserved when omitted; "
        "new users default to none."
    ),
)
@click.option(
    "--groups",
    metavar="GROUP_LIST",
    help="Comma-separated console-server group names.",
)
@click.option(
    "--password",
    metavar="VALUE",
    help=(
        "Password value for non-interactive use. The value may be visible "
        "in process arguments and shell history."
    ),
)
@click.option(
    "--prompt-password",
    is_flag=True,
    help="Prompt securely to set or replace the Linux password.",
)
def user_add(
    username: str,
    role: str | None,
    groups: str | None,
    password: str | None,
    prompt_password: bool,
) -> None:
    """Create or update a console-server user."""

    password = _resolve_password(
        password,
        prompt_password,
        required=False,
    )

    try:
        manager = create_default_manager()
        manager.set_user_config(
            username,
            password,
            role,
            _parse_groups(groups),
        )
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error


@user.command(name="password")
@click.argument("username")
@click.option(
    "--password",
    metavar="VALUE",
    help=(
        "Password value for non-interactive use. The value may be visible "
        "in process arguments and shell history."
    ),
)
@click.option(
    "--prompt-password",
    is_flag=True,
    help="Prompt securely for the new password.",
)
def user_password(
    username: str,
    password: str | None,
    prompt_password: bool,
) -> None:
    """Set the password of an existing Linux user."""

    password = _resolve_password(
        password,
        prompt_password,
        required=True,
    )

    try:
        manager = create_default_manager()
        manager.set_user_password(username, password)
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error


@user.command(name="delete")
@click.argument("username")
def user_delete(username: str) -> None:
    """Delete a console-server user."""

    try:
        manager = create_default_manager()
        manager.delete_user(username)
    except ConsoleServerManagerError as error:
        raise click.ClickException(str(error)) from error
