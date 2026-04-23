#!/usr/bin/env python3

import os
import pwd
import sys
import time
import json
import threading
import queue
import subprocess
from enum import Enum, auto
from uuid import uuid4
import click

# =========================
# Session / Role / State
# =========================

class UserRole(Enum):
    ADMIN = "admin"
    CONSOLE_USER = "console_user"
    OPERATOR = "operator"
    OBSERVER = "observer"

# Role-based command decorator for Click
def role_required(min_role):
    def decorator(f):
        f._min_role = min_role
        # If this is a Click command, also set on the command object
        if hasattr(f, 'command'):
            f.command._min_role = min_role
        return f
    return decorator

# Custom Click Group to hide commands from help if user lacks role
class RoleAwareGroup(click.Group):
    def get_help(self, ctx):
        # Use global _current_user_role for help filtering
        global _current_user_role
        user_role = _current_user_role
        orig_list_commands = self.list_commands

        def filtered_list_commands(ctx):
            cmds = orig_list_commands(ctx)
            if not user_role:
                print("[DEBUG] No user_role set, returning all commands")
                return cmds
            filtered = []
            for cmd in cmds:
                command_obj = self.get_command(ctx, cmd)
                min_role = getattr(command_obj, '_min_role', None)
                print(f"[DEBUG] Command: {cmd}, min_role: {min_role}, user_role: {user_role}")
                if min_role is None or user_role_allowed(user_role, min_role):
                    print(f"[DEBUG] -> ALLOWED")
                    filtered.append(cmd)
                else:
                    print(f"[DEBUG] -> HIDDEN")
            return filtered

        self.list_commands = filtered_list_commands
        return super().get_help(ctx)

def user_role_allowed(user_role, min_role):
    # Order: ADMIN > CONSOLE_USER > OPERATOR > OBSERVER
    order = [UserRole.ADMIN, UserRole.CONSOLE_USER, UserRole.OPERATOR, UserRole.OBSERVER]
    try:
        return order.index(user_role) <= order.index(min_role)
    except Exception:
        return False

class SessionState(Enum):
    INIT = auto()
    ATTACHED = auto()
    CLOSED = auto()


class Session:
    def __init__(self, user, role, ip=None, port=None):
        self.session_id = str(uuid4())
        self.user = user
        self.role = role
        self.line_id = None
        self.ip = ip
        self.port = port

        self.state = SessionState.INIT
        self.can_write = False

        self.tx_callback = None  # write back to SSH stdout

    def attach(self, line_id):
        self.line_id = line_id
        self.state = SessionState.ATTACHED

    def grant_write(self):
        self.can_write = True

    def revoke_write(self):
        self.can_write = False

    def on_client_input(self, data: bytes):
        if not self.can_write:
            if self.tx_callback:
                self.tx_callback(b"\r\n[Permission denied]\r\n")
            return None
        return data

    def on_serial_output(self, data: bytes):
        if self.tx_callback:
            self.tx_callback(data)

    def __repr__(self):
        ip_port = f" ip={self.ip} port={self.port}" if self.ip or self.port else ""
        return f"<Session {self.user} role={self.role.value} write={self.can_write}{ip_port}>"


# =========================
# Fake Serial + Mock ser2net
# =========================

class FakeSerialDevice:
    def __init__(self):
        self.rx = queue.Queue()
        self.tx = queue.Queue()
        self.running = False
        self._thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        time.sleep(0.5)
        self.tx.put(b"\r\nBooting device...\r\nlogin: ")
        while self.running:
            try:
                data = self.rx.get(timeout=0.1)
                cmd = data.strip()
                if cmd == b"admin":
                    self.tx.put(b"\r\nPassword: ")
                elif cmd == b"password":
                    self.tx.put(b"\r\nWelcome!\r\n# ")
                else:
                    self.tx.put(b"\r\nunknown command: " + cmd + b"\r\n# ")
            except queue.Empty:
                pass


class MockSer2Net:
    def __init__(self, fake_serial):
        self.serial = fake_serial

    def send(self, data: bytes):
        self.serial.rx.put(data)

    def recv(self, timeout=0.1):
        try:
            return self.serial.tx.get(timeout=timeout)
        except queue.Empty:
            return None


# =========================
# Policy Engine
# =========================

class PolicyEngine:
    def __init__(self):
        self.active_writer = {}  # line_id -> session_id

    def attach(self, session: Session):
        line = session.line_id

        if session.role == UserRole.ADMIN:
            self.active_writer[line] = session.session_id
            return True

        if line not in self.active_writer:
            self.active_writer[line] = session.session_id
            return True

        return False

    def override(self, session: Session):
        self.active_writer[session.line_id] = session.session_id


# =========================
# Session Manager
# =========================

class SessionManager:
    def __init__(self, ser2net):
        self.ser2net = ser2net
        self.sessions = []
        self.line_sessions = {}
        self.policy = PolicyEngine()
        threading.Thread(target=self._rx_loop, daemon=True).start()

    def add_session(self, session: Session):
        self.sessions.append(session)

    def attach_line(self, session: Session, line_id: int):
        session.attach(line_id)
        self.line_sessions.setdefault(line_id, []).append(session)

        can_write = self.policy.attach(session)
        if can_write:
            session.grant_write()
        else:
            session.revoke_write()

        return can_write

    def handle_tx(self, session: Session, data: bytes):
        if session.can_write:
            self.ser2net.send(data)

    def _rx_loop(self):
        while True:
            data = self.ser2net.recv()
            if not data:
                continue
            for sess in self.sessions:
                if sess.state == SessionState.ATTACHED:
                    sess.on_serial_output(data)


# =========================
# CLI
# =========================

CLI_MODE = 0
SERIAL_MODE = 1


def write_stdout(data: bytes):
    os.write(sys.stdout.fileno(), data)



# =========================
# Click CLI Implementation
# =========================

DEBUG_STATE_FILE = "/tmp/console-cli.debug"

def _run_status_cmd(cmd_args, quiet_on_success=False):
    """Helper to run commands using the status.py utility."""
    base_path = os.path.dirname(os.path.abspath(__file__))
    status_script = "/usr/local/bin/seriald-status"

    if not os.path.exists(status_script):
        click.echo(f"Error: {status_script} utility not found.", err=True)
        return 1, "", f"{status_script} not found"

    cmd = [sys.executable, status_script] + cmd_args

    is_debug = os.path.exists(DEBUG_STATE_FILE) or '--debug' in sys.argv
    if quiet_on_success and not is_debug:
        cmd.append("--quiet")

    if is_debug:
        click.echo(f"[DEBUG] Running status command: {' '.join(cmd)}", err=True)

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr
    except Exception as e:
        return 1, "", str(e)


def _normalize_cell(value):
    if value is None:
        return "-"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "-"
    return str(value)


def _print_table(headers, rows):
    normalized_rows = [[_normalize_cell(cell) for cell in row] for row in rows]
    widths = [len(str(h)) for h in headers]
    for row in normalized_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    header_line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    click.echo(header_line)
    click.echo(sep_line)
    for row in normalized_rows:
        click.echo("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _render_product_info_as_table(info_data):
    """Render the product info as a table."""
    if not isinstance(info_data, dict) or not info_data:
        return False

    rows = []
    for key in sorted(info_data.keys()):
        value = info_data.get(key)
        rows.append([key, value])
    _print_table(["Key", "Value"], rows)
    return True


def _render_config_section_as_table(config_data, section_name):
    if section_name == "users":
        users = config_data.get("users", {})
        if not isinstance(users, dict):
            return False
        rows = []
        for username in sorted(users.keys()):
            user_cfg = users.get(username, {}) or {}
            groups = user_cfg.get("groups", [])
            role = user_cfg.get("role", "-")
            rows.append([username, groups, role])
        _print_table(["user", "group", "role"], rows)
        return True

    if section_name == "groups":
        groups = config_data.get("groups", {})
        if not isinstance(groups, dict):
            return False
        rows = []
        for group_name in sorted(groups.keys()):
            group_cfg = groups.get(group_name, {}) or {}
            port_list = group_cfg.get("port_list", [])
            role = group_cfg.get("role", "-")
            rows.append([group_name, port_list, role])
        _print_table(["group", "port_list", "role"], rows)
        return True

    return False


def _render_lines_section(config_data):
    lines = config_data.get("lines", {})
    if not isinstance(lines, dict) or not lines:
        return False

    def _line_sort_key(value):
        text = str(value).strip()
        if text.isdigit():
            return (0, int(text), text)
        return (1, text)

    display_fields = [
        "line",
        "name",
        "label",
        "mode",
        "max_clients",
        "idle_timeout",
        "baudrate",
        "databits",
        "stopbits",
        "parity",
        "flowcontrol",
        "interface",
    ]
    rows = []
    for line_key in sorted(lines.keys(), key=_line_sort_key):
        line_cfg = lines.get(line_key, {}) or {}
        rows.append([
            line_key,
            line_cfg.get("name"),
            line_cfg.get("label"),
            line_cfg.get("mode"),
            line_cfg.get("max_clients"),
            line_cfg.get("idle_timeout"),
            line_cfg.get("baudrate"),
            line_cfg.get("databits"),
            line_cfg.get("stopbits"),
            line_cfg.get("parity"),
            line_cfg.get("flowcontrol"),
            line_cfg.get("interface"),
        ])
    _print_table(display_fields, rows)

    return True


def _display_show_output(stdout, *, show_groups=False, show_users=False, show_line=False):
    if not stdout:
        return

    try:
        parsed = json.loads(stdout)
    except Exception:
        click.echo(stdout, nl=False)
        return

    rendered_any = False
    if show_users:
        rendered_any = _render_config_section_as_table(parsed, "users") or rendered_any
    if show_groups:
        if rendered_any:
            click.echo("")
        rendered_any = _render_config_section_as_table(parsed, "groups") or rendered_any
    if show_line:
        if rendered_any:
            click.echo("")
        rendered_any = _render_lines_section(parsed) or rendered_any

    if rendered_any:
        return

    click.echo(stdout, nl=False)


def _normalize_line_selector(line_id):
    if line_id is None:
        return None
    normalized = str(line_id).strip()
    if not normalized:
        return None
    if normalized.lower() == "all":
        return "all"
    return normalized

def get_user_and_role():
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        user = os.getenv("LOGNAME") or os.getenv("USER", "unknown")

    # Get role from seriald-status via subprocess
    retcode, stdout, stderr = _run_status_cmd(["user-role", user], quiet_on_success=True)

    role_str = None
    if retcode == 0 and stdout:
        role_str = stdout.strip()

    if role_str and role_str in UserRole._value2member_map_:
        role = UserRole(role_str)
    else:
        is_debug = os.path.exists(DEBUG_STATE_FILE) or '--debug' in sys.argv
        if is_debug:
            click.echo(f"Warning: Failed to get role for '{user}'. "
                       f"Retcode: {retcode}, Stderr: {stderr.strip()}", err=True)
        # Default to a safe, non-privileged role if lookup fails
        role = UserRole.OPERATOR
    return user, role

# Global user/role for help filtering
_current_user = None
_current_user_role = None

@click.group(cls=RoleAwareGroup)
@click.option('--debug', is_flag=True, help='Enable detailed debug output for this command.')
@click.pass_context
def cli(ctx, debug):
    """Console Server CLI (Click version)"""
    # print("[debug-cli] Initializing console-cli...")
    ctx.ensure_object(dict)

    # Store debug flag in context if present
    if debug:
        ctx.obj['debug'] = True

    user, role = get_user_and_role()
    # print(f"Logged in as: {user}, Role: {role.value}")
    ctx.obj['user'] = user
    ctx.obj['role'] = role
    session = Session(user, role)
    session.tx_callback = write_stdout
    fake_serial = FakeSerialDevice()
    ser2net = MockSer2Net(fake_serial)
    manager = SessionManager(ser2net)
    manager.add_session(session)
    ctx.obj['session'] = session
    ctx.obj['manager'] = manager
    ctx.obj['fake_serial'] = fake_serial


@cli.command()
def debug():
    """Enable persistent debug mode."""
    try:
        with open(DEBUG_STATE_FILE, "w") as f:
            f.write("enabled")
        click.echo("Debug mode enabled.")
    except IOError as e:
        click.echo(f"Error enabling debug mode: {e}", err=True)

@cli.command()
def no_debug():
    """Disable persistent debug mode."""
    try:
        if os.path.exists(DEBUG_STATE_FILE):
            os.remove(DEBUG_STATE_FILE)
        click.echo("Debug mode disabled.")
    except IOError as e:
        click.echo(f"Error disabling debug mode: {e}", err=True)

@cli.command()
@click.argument('line_id', type=int)
def connect(line_id):
    "Connect to a specific serial line via seriald-client."
    args = ["/usr/bin/python3", "/usr/local/bin/seriald-client", "--line", str(line_id)]
    click.echo(f"[Connecting to line {line_id}.]")
    try:
        subprocess.run(args)
        click.echo("[Detached]")
    except Exception:
        click.echo("[Failed to run seriald client]")


@cli.command()
@click.argument('line', type=int, default=1)
@click.pass_context
def open_line(ctx, line):
    "Open a line locally (demo backend)."
    session = ctx.obj['session']
    manager = ctx.obj['manager']
    fake_serial = ctx.obj['fake_serial']
    if not user_role_allowed(session.role, UserRole.CONSOLE_USER):
        click.echo("Permission denied: requires CONSOLE_USER or higher.")
        return
    can_write = manager.attach_line(session, line)
    fake_serial.start()
    click.echo("[Attached as writer]" if can_write else "[Attached as observer]")
    click.echo("Tip: in device mode, type 'shell' to open a host shell.")
    click.echo("Tip: from that host shell, type 'exit' or press Ctrl-D to return to the device session.")
    click.echo("Tip: type 'exit' at the device prompt to detach back to this CLI.")
open_line._min_role = UserRole.ADMIN # only admin can open line in this demo


@cli.command()
def shell():
    "Switch to host shell."
    try:
        user_shell = pwd.getpwuid(os.getuid()).pw_shell or "/bin/bash"
    except Exception:
        user_shell = "/bin/bash"
    if os.path.basename(user_shell) in ("console-cli", "console_cli.py"):
        user_shell = "/bin/bash"
    click.echo(f"[Switching to shell: {user_shell}]")
    os.execlp(user_shell, os.path.basename(user_shell))
shell._min_role = UserRole.ADMIN  # the role should be admin

@cli.command()
def exit():
    "Exit the CLI."
    click.echo("Bye")
    sys.exit(0)

# =========================
# Configuration Commands
# =========================

@click.group()
def config():
    """Commands for configuring serial ports and operations."""
    pass

@config.command()
@click.argument('port_number', type=int)
@click.option('--baudrate', type=click.Choice([
    '300', '1200', '2400', '4800', '9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600'
]), help='Sets the baud rate.')
@click.option('--databits', type=click.Choice(['5', '6', '7', '8']), help='Sets the data bits.')
@click.option('--parity', type=click.Choice(['none', 'even', 'odd', 'mark', 'space']), help='Sets the parity.')
@click.option('--stopbits', type=click.Choice(['1', '2']), help='Sets the stop bits.')
@click.option('--flowcontrol', type=click.Choice(['none', 'rtscts', 'xonxoff']), help='Sets flow control.')
def port(port_number, baudrate, databits, parity, stopbits, flowcontrol):
    """Configures the physical serial line settings for a specific port."""
    cmd_args = ["config-port", str(port_number)]
    if baudrate:
        cmd_args.extend(["--baudrate", baudrate])
    if databits:
        cmd_args.extend(["--databits", databits])
    if parity:
        cmd_args.extend(["--parity", parity])
    if stopbits:
        cmd_args.extend(["--stopbits", str(stopbits)])
    if flowcontrol:
        cmd_args.extend(["--flowcontrol", flowcontrol])

    if len(cmd_args) == 2:
        click.echo("No settings provided to configure.", err=True)
        return

    retcode, stdout, stderr = _run_status_cmd(cmd_args, quiet_on_success=True)
    if retcode == 0:
        click.echo("Set serial port configuration    : Success")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo("Set serial port configuration    : Failed", err=True)
        if stderr.strip(): click.echo(stderr, err=True)
        sys.exit(1)

@config.command()
@click.argument('port_number', type=int)
@click.option('--mode', type=click.Choice(['exclusive', 'shared']), help='Sets the connection mode.')
@click.option('--max-clients', type=click.IntRange(1, 4), help='Sets the maximum number of concurrent clients (1-4).')
@click.option('--idle-timeout', type=int, help='Sets the idle timeout in seconds. Use 0 to disable.')
@click.option('--label', type=str, help='Sets a user-friendly nickname for the device.')
def operation(port_number, mode, max_clients, idle_timeout, label):
    """Configures the server's operational behavior for a specific serial line."""
    cmd_args = ["config-op", str(port_number)]
    if mode:
        cmd_args.extend(["--mode", mode])
    if max_clients is not None:
        cmd_args.extend(["--max-clients", str(max_clients)])
    if idle_timeout is not None:
        cmd_args.extend(["--idle-timeout", str(idle_timeout)])
    if label is not None:
        cmd_args.extend(["--label", label])

    if len(cmd_args) == 2:
        click.echo("No settings provided to configure.", err=True)
        return

    retcode, stdout, stderr = _run_status_cmd(cmd_args, quiet_on_success=True)
    if retcode == 0:
        click.echo("Set serial operation configuration    : Success")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo("Set serial operation configuration    : Failed", err=True)
        if stderr.strip(): click.echo(stderr, err=True)
        sys.exit(1)

@config.command(name='save')
def save():
    """Saves the current running configuration to the startup-config (config.json)."""
    retcode, stdout, stderr = _run_status_cmd(['save-config'], quiet_on_success=True)
    if retcode == 0:
        click.echo("Configuration saved successfully.")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo("Failed to save configuration.", err=True)
        if stderr.strip(): click.echo(stderr, err=True)
        sys.exit(1)

@config.group()
def user():
    """Manage users and their properties."""
    pass

@user.command(name='add')
@click.argument('username', type=str)
@click.option('--role', type=click.Choice(['operator', 'console_user', 'admin', 'none']), help='Assigns a specific role to the user.')
@click.option('--groups', type=str, help='Comma-separated list of groups.')
@click.option('--password', type=str, help='Set or update the user password (local Linux account only).')
def user_add(username, role, groups, password):
    """Creates a new user or modifies an existing user's properties."""

    cmd_args = ["config-user", username]
    if role:
        cmd_args.extend(["--role", role])
    if groups:
        cmd_args.extend(["--groups", groups])
    if password:
        cmd_args.extend(["--password", password])

    retcode, stdout, stderr = _run_status_cmd(cmd_args, quiet_on_success=True)
    if retcode == 0:
        click.echo("User configuration updated successfully.")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo("Failed to update user configuration.", err=True)
        detail = stderr.strip() or stdout.strip()
        if detail:
            click.echo(detail, err=True)
        sys.exit(1)

@user.command(name='delete')
@click.argument('username', type=str)
def user_delete(username):
    """Deletes a user."""
    retcode, stdout, stderr = _run_status_cmd(["config-no-user", username], quiet_on_success=True)
    if retcode == 0:
        click.echo(f"User '{username}' deleted successfully.")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo(f"Failed to delete user '{username}'.", err=True)
        if stderr.strip(): click.echo(stderr, err=True)
        sys.exit(1)

def parse_ports(ports_str: str) -> str:
    """Parses a string of ports, which can include ranges (e.g., '1-5') and individual numbers."""
    if not ports_str:
        return ""

    final_ports = []
    parts = ports_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                if start > end:
                    start, end = end, start
                final_ports.extend(range(start, end + 1))
            except ValueError:
                # Handle cases like '1-a' or 'a-5' gracefully
                click.echo(f"Warning: Invalid range '{part}' ignored.", err=True)
                continue
        else:
            try:
                final_ports.append(int(part))
            except ValueError:
                click.echo(f"Warning: Invalid port number '{part}' ignored.", err=True)
                continue

    # Return a comma-separated string of unique, sorted port numbers
    return ",".join(map(str, sorted(list(set(final_ports)))))

@config.group()
def group():
    """Manage groups and their properties."""
    pass

@group.command(name='add')
@click.argument('groupname', type=str)
@click.option('--ports', type=str, help='Comma-separated list of port numbers.')
@click.option('--role', type=click.Choice(['operator', 'console_user', 'admin', 'none']), help='Assigns a specific role to the group.')
def group_add(groupname, ports, role):
    """Creates a new group or modifies an existing group's properties."""
    cmd_args = ["config-group", groupname]
    if ports:
        parsed_ports = parse_ports(ports)
        if parsed_ports:
            cmd_args.extend(["--ports", parsed_ports])
    if role:
        cmd_args.extend(["--role", role])

    retcode, stdout, stderr = _run_status_cmd(cmd_args, quiet_on_success=True)
    if retcode == 0:
        click.echo("Group configuration updated successfully.")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo("Failed to update group configuration.", err=True)
        detail = stderr.strip() or stdout.strip()
        if detail:
            click.echo(detail, err=True)
        sys.exit(1)

@group.command(name='delete')
@click.argument('groupname', type=str)
def group_delete(groupname):
    """Deletes a group."""
    retcode, stdout, stderr = _run_status_cmd(["config-no-group", groupname], quiet_on_success=True)
    if retcode == 0:
        click.echo(f"Group '{groupname}' deleted successfully.")
        if stdout.strip(): click.echo(stdout)
    else:
        click.echo(f"Failed to delete group '{groupname}'.", err=True)
        detail = stderr.strip() or stdout.strip()
        if detail:
            click.echo(detail, err=True)
        sys.exit(1)

cli.add_command(config)

@click.group()
def show():
    """Show running system information."""
    pass

@show.command(name='running-config')
@click.option('--line', 'line_id', help='Display config for a specific line (ID/label) or all.')
@click.option('--groups', is_flag=True, help='Display groups configuration.')
@click.option('--users', is_flag=True, help='Display users configuration.')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON.')
def show_running_config(line_id, groups, users, output_json):
    """Displays the current, active (in-memory) configuration."""
    cmd_args = ['show-running-config']
    normalized_line_id = _normalize_line_selector(line_id)
    if normalized_line_id:
        cmd_args.extend(['--line', normalized_line_id])
    if groups:
        cmd_args.append('--groups')
    if users:
        cmd_args.append('--users')
    retcode, stdout, stderr = _run_status_cmd(cmd_args)
    if output_json:
        if stdout:
            click.echo(stdout, nl=False)
    else:
        _display_show_output(
            stdout,
            show_groups=groups,
            show_users=users,
            show_line=normalized_line_id is not None,
        )
    if retcode != 0 and stderr.strip():
        click.echo(stderr, err=True)

@show.command(name='startup-config')
@click.option('--line', 'line_id', help='Display config for a specific line (ID/label) or all.')
@click.option('--groups', is_flag=True, help='Display groups configuration.')
@click.option('--users', is_flag=True, help='Display users configuration.')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON.')
def show_startup_config(line_id, groups, users, output_json):
    """Displays the saved (startup) configuration."""
    cmd_args = ['show-startup-config']
    normalized_line_id = _normalize_line_selector(line_id)
    if normalized_line_id:
        cmd_args.extend(['--line', normalized_line_id])
    if groups:
        cmd_args.append('--groups')
    if users:
        cmd_args.append('--users')
    retcode, stdout, stderr = _run_status_cmd(cmd_args)
    if output_json:
        if stdout:
            click.echo(stdout, nl=False)
    else:
        _display_show_output(
            stdout,
            show_groups=groups,
            show_users=users,
            show_line=normalized_line_id is not None,
        )
    if retcode != 0 and stderr.strip():
        click.echo(stderr, err=True)

@show.command(name='sessions')
@click.option('--line', 'line_id', type=int, help='Filter sessions for a specific line ID.')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON.')
def show_sessions_cmd(line_id, output_json):
    """Displays active client sessions."""
    cmd_args = ['sessions']
    if line_id is not None:
        cmd_args.extend(['--line', str(line_id)])
    if output_json:
        cmd_args.append('--json')
    retcode, stdout, stderr = _run_status_cmd(cmd_args)
    if stdout:
        click.echo(stdout, nl=False)
    if retcode != 0 and stderr.strip():
        click.echo(stderr, err=True)

@show.command(name='product-info')
@click.option('--json', 'output_json', is_flag=True, help='Output raw JSON.')
def show_product_info(output_json):
    """Displays product information (base_port, limits, etc.)."""
    cmd_args = ['show-product-info']
    retcode, stdout, stderr = _run_status_cmd(cmd_args)

    if output_json or retcode != 0:
        # For JSON output or errors, show raw output
        if stdout:
            click.echo(stdout, nl=False)
    else:
        # For table format, parse and render
        if stdout:
            try:
                info_data = json.loads(stdout)
                _render_product_info_as_table(info_data)
            except Exception:
                click.echo(stdout, nl=False)

    if retcode != 0 and stderr.strip():
        click.echo(stderr, err=True)

cli.add_command(show)

def repl():
    """Interactive REPL for console-cli (Click version)."""
    import shlex

    print("[debug-repl] Initializing console-repl...")
    try:
        import readline
    except ImportError:
        readline = None
    click.echo("Console Server CLI (interactive mode)")
    click.echo("Type 'help' or '?' for commands. Type 'exit' or Ctrl-D to quit.")
    current_user, current_user_role = get_user_and_role()
    current_ip = os.environ.get("SSH_CLIENT_IP")
    current_port = os.environ.get("SSH_CLIENT_PORT")
    click.echo(f"Your user: {current_user}")
    click.echo(f"Your role: {current_user_role.value}")
    if current_ip or current_port:
        click.echo(f"Your IP: {current_ip}, Port: {current_port}")
    if readline:
        histfile = os.path.expanduser("~/.console_cli_history")
        try:
            readline.read_history_file(histfile)
        except FileNotFoundError:
            pass
        import atexit
        atexit.register(lambda: readline.write_history_file(histfile))
    ctx = None
    while True:
        try:
            line = input('console-cli> ').strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye")
            break
        if not line:
            continue
        if line in ('exit', 'quit'):
            click.echo("Bye")
            break
        if line in ('help', '?'):
            # Show only commands allowed for the current user/role, with debug output
            user_role = current_user_role
            click.echo("\nAvailable commands:")
            for cmd_name in cli.commands:
                cmd_obj = cli.get_command(None, cmd_name)
                min_role = getattr(cmd_obj, '_min_role', None)
                if min_role is None or user_role_allowed(user_role, min_role):
                    click.echo(f"  {cmd_name:14} {cmd_obj.help}")
            click.echo("Type 'exit' or Ctrl-D to quit.")
            continue
        # Parse and dispatch command
        try:
            args = shlex.split(line)
        except Exception as e:
            click.echo(f"Parse error: {e}")
            continue
        try:
            cli.main(args=args, standalone_mode=True, obj={})
        except SystemExit:
            pass
        except Exception as e:
            click.echo(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) == 1:
        repl()
    else:
        cli(obj={})


# /etc/passwd 裡：
# alice:x:1001:1001::/home/alice:/usr/bin/console-cli
# bob:x:1002:1002::/home/bob:/usr/bin/console-cli

# sudo install -m 0755 console_cli.py /usr/local/bin/console-cli