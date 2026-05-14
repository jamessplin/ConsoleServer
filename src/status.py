#!/usr/bin/env python3
#
# Usage:
#   status.py sessions           # Show daemon sessions
#   status.py config             # Show config from server
#   status.py user-role USERNAME # Show effective role for user
#


import asyncio
import json
import os
import sys
import subprocess


def max_clients_1_to_4(value):
    ivalue = int(value)
    if ivalue < 1 or ivalue > 4:
        raise ValueError("must be an integer between 1 and 4")
    return ivalue


_quiet_mode = False

def qprint(*args, **kwargs):
    """Quiet print - only prints if quiet mode is not enabled."""
    if not _quiet_mode:
        print(*args, **kwargs)

def eprint(*args, **kwargs):
    """Always print to stderr, even in quiet mode."""
    print(*args, file=sys.stderr, **kwargs)

def write_stdout(data: bytes):
    # This is a low-level writer, qprint should be used for conditional output
    os.write(sys.stdout.fileno(), data)

async def print_config_from_server(host: str, port: int):
    # Fetch config from the running server using the protocol
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(json.dumps({"op": "config"}).encode() + b"\n")
    await writer.drain()
    line = await reader.readline()
    try:
        msg = json.loads(line.decode())
    except Exception:
        msg = {"op": "error", "msg": "invalid response"}
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    if msg.get("op") == "config":
        import json as _json
        pretty = _json.dumps(msg.get("config", {}), indent=2)
        pretty = pretty.replace("\n", "\r\n")
        write_stdout(pretty.encode() + b"\r\n")
    else:
        write_stdout((f"[Failed to fetch config: {msg.get('msg','unknown error')}]\r\n").encode())
    sys.exit(0)


async def get_status(host: str, port: int, line_id: int = None) -> dict:
    reader, writer = await asyncio.open_connection(host, port)
    msg = {"op": "status"}
    if line_id is not None:
        msg["line"] = line_id
    writer.write(json.dumps(msg).encode() + b"\n")
    await writer.drain()
    # status is a single-line response
    line = await reader.readline()
    try:
        msg = json.loads(line.decode())
    except Exception:
        msg = {"op": "error", "msg": "invalid response"}
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    return msg


def render_status(status: dict) -> bytes:
    if status.get("op") != "status":
        return (f"[Error] {status.get('msg','unknown error')}\n").encode()
    lines = status.get("lines", [])
    out = []
    out.append("Daemon Sessions:\n")
    if not lines:
        out.append("(no lines)\n")
        return "".join(out).encode()
    for entry in sorted(lines, key=lambda x: x.get("line", 0)):
        line = entry.get("line")
        mode = entry.get("mode")
        writer_user = entry.get("writer")
        counts = entry.get("counts", {})
        out.append(f"- line {line} [{mode}] : writer={writer_user or 'none'} "
                   f"(clients={counts.get('clients',0)}, writers={counts.get('writers',0)}, observers={counts.get('observers',0)})\n")
        for c in entry.get("clients", []):
            ip = c.get('ip')
            port = c.get('port')
            ip_port = f" ip={ip}" if ip else ""
            ip_port += f" port={port}" if port else ""
            idle_timeout = c.get('idle_timeout')
            time_left = c.get('time_left')
            timeout_info = ""
            if idle_timeout is not None:
                if time_left is not None:
                    timeout_info = f" [timeout={idle_timeout}s, left={time_left}s]"
                else:
                    timeout_info = f" [timeout={idle_timeout}s]"
            out.append(f"    - {c.get('user','unknown')} role={c.get('role','?')}{ip_port}{timeout_info}\n")
    return "".join(out).encode()


async def send_config_update(host: str, port: int, msg: dict, expected_op: str = None) -> tuple[bool, str]:
    """Send config update and return (ok, error_message)."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(json.dumps(msg).encode() + b"\n")
        await writer.drain()

        response_line = await reader.readline()
        try:
            response = json.loads(response_line.decode())
        except Exception:
            return False, "invalid response"

        if response.get("op") == "error":
            return False, response.get("msg", "unknown error")

        if expected_op and response.get("op") != expected_op:
            return False, f"unexpected response op: {response.get('op')}"

        if response.get("ok"):
            qprint("Configuration updated successfully.")
            return True, ""

        return False, response.get("msg", "unknown error")

    except ConnectionRefusedError:
        return False, "Connection refused. Is the seriald server running?"
    except Exception as e:
        return False, f"An error occurred: {e}"
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except NameError: # writer was not created
            pass
        except Exception: # other errors
            pass
    return False, "unknown error"


def normalize_line_selector(line_id):
    if line_id is None:
        return None
    normalized = str(line_id).strip()
    if not normalized:
        return None
    if normalized.lower() == "all":
        return "all"
    return normalized

async def main():
    global _quiet_mode
    import argparse
    p = argparse.ArgumentParser(description="seriald status utility")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25001)
    p.add_argument("-q", "--quiet", action="store_true", help="suppress informational output")
    subparsers = p.add_subparsers(dest="command", required=True)

    sp_sessions = subparsers.add_parser("sessions", help="show daemon sessions")
    sp_sessions.add_argument("--line", type=int, help="filter by line ID")
    sp_sessions.add_argument("--json", action="store_true", help="output raw JSON")
    sp_config = subparsers.add_parser("config", help="show config.json from server")
    sp_user_role = subparsers.add_parser("user-role", help="show effective role for user")
    sp_user_role.add_argument("username", metavar="USERNAME", help="username to query")

    # New subparser for config-port
    sp_config_port = subparsers.add_parser("config-port", help="configure serial port settings")
    sp_config_port.add_argument("line", type=int, help="the line number to configure")
    sp_config_port.add_argument("--baudrate", type=int, help="sets the baud rate")
    sp_config_port.add_argument("--databits", type=int, choices=[5, 6, 7, 8], help="sets the data bits (5, 6, 7, 8)")
    sp_config_port.add_argument("--parity", choices=['none', 'even', 'odd', 'mark', 'space'], help="sets the parity")
    sp_config_port.add_argument("--stopbits", type=int, choices=[1, 2], help="sets the stop bits")
    sp_config_port.add_argument("--flowcontrol", choices=['none', 'rtscts'], help="sets flow control")
    sp_config_port.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # New subparser for config-op
    sp_config_op = subparsers.add_parser("config-op", help="configure port operational settings")
    sp_config_op.add_argument("line", type=int, help="the line number to configure")
    sp_config_op.add_argument("--mode", choices=['exclusive', 'shared'], help="sets the connection mode")
    sp_config_op.add_argument("--max-clients", type=max_clients_1_to_4, help="sets the maximum number of concurrent clients (1-4)")
    sp_config_op.add_argument("--idle-timeout", type=int, help="sets the idle timeout in seconds")
    sp_config_op.add_argument("--label", type=str, help="sets a user-friendly nickname for the device")
    sp_config_op.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # New subparsers for show-running-config and show-startup-config
    sp_show_running = subparsers.add_parser("show-running-config", help="show running configuration")
    sp_show_running.add_argument("--line", dest="line_id", type=str, help="display config for a specific line (ID/label) or all")
    sp_show_running.add_argument("--groups", action="store_true", help="display groups configuration")
    sp_show_running.add_argument("--users", action="store_true", help="display users configuration")
    sp_show_running.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    sp_show_startup = subparsers.add_parser("show-startup-config", help="show startup configuration")
    sp_show_startup.add_argument("--line", dest="line_id", type=str, help="display config for a specific line (ID/label) or all")
    sp_show_startup.add_argument("--groups", action="store_true", help="display groups configuration")
    sp_show_startup.add_argument("--users", action="store_true", help="display users configuration")
    sp_show_startup.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # New subparser for show-product-info
    sp_show_product_info = subparsers.add_parser("show-product-info", help="show product information")
    sp_show_product_info.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # New subparser for save-config
    sp_save_config = subparsers.add_parser("save-config", help="save running-config to startup-config")
    sp_save_config.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # User management
    sp_config_user = subparsers.add_parser("config-user", help="create or modify a user")
    sp_config_user.add_argument("username", type=str, help="the username to configure")
    sp_config_user.add_argument("--role", choices=['operator', 'console_user', 'admin', 'none'], help="assigns a specific role to the user")
    sp_config_user.add_argument("--groups", type=str, help="comma-separated list of groups")
    sp_config_user.add_argument("--password", type=str, help="set or update the user password (local Linux account only)")
    sp_config_user.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    sp_config_no_user = subparsers.add_parser("config-no-user", help="delete a user")
    sp_config_no_user.add_argument("username", type=str, help="the username to delete")
    sp_config_no_user.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    # Group management
    sp_config_group = subparsers.add_parser("config-group", help="create or modify a group")
    sp_config_group.add_argument("groupname", type=str, help="the group name to configure")
    sp_config_group.add_argument("--ports", type=str, help="comma-separated list of port numbers")
    sp_config_group.add_argument("--role", choices=['operator', 'console_user', 'admin', 'none'], help="assigns a default role to the group")
    sp_config_group.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    sp_config_no_group = subparsers.add_parser("config-no-group", help="delete a group")
    sp_config_no_group.add_argument("groupname", type=str, help="the group name to delete")
    sp_config_no_group.add_argument("-q", "--quiet", action="store_true", help="suppress output (ignored)")

    args = p.parse_args()
    if args.quiet:
        _quiet_mode = True

    if args.command == "sessions":
        st = await get_status(args.host, args.port, line_id=args.line)
        if args.json:
            import json as _json
            pretty = _json.dumps(st, indent=2)
            write_stdout(pretty.encode() + b"\n")
        else:
            write_stdout(render_status(st))
        return

    if args.command == "config":
        await print_config_from_server(args.host, args.port)
        return

    if args.command in ["show-running-config", "show-startup-config"]:
        op = "config" if args.command == "show-running-config" else "startup-config"
        msg = {"op": op}
        line_selector = normalize_line_selector(args.line_id)
        if line_selector:
            msg["line"] = line_selector
        if args.groups:
            msg["groups"] = True
        if args.users:
            msg["users"] = True

        reader, writer = await asyncio.open_connection(args.host, args.port)
        writer.write(json.dumps(msg).encode() + b"\n")
        await writer.drain()
        line = await reader.readline()
        try:
            response = json.loads(line.decode())
        except Exception:
            response = {"op": "error", "msg": "invalid response"}
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        if response.get("op") == op:
            import json as _json
            config_data = response.get("config", {})
            pretty = _json.dumps(config_data, indent=2)
            write_stdout(pretty.encode() + b"\n")
        else:
            write_stdout((f"[Failed to fetch config: {response.get('msg','unknown error')}]\r\n").encode())
        sys.exit(0)

    if args.command == "show-product-info":
        msg = {"op": "product-info"}
        reader, writer = await asyncio.open_connection(args.host, args.port)
        writer.write(json.dumps(msg).encode() + b"\n")
        await writer.drain()
        line = await reader.readline()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        try:
            response = json.loads(line.decode())
        except Exception:
            response = {"op": "error", "msg": "invalid response"}

        if response.get("op") == "product-info":
            import json as _json
            data = response.get("data", {})
            pretty = _json.dumps(data, indent=2)
            write_stdout(pretty.encode() + b"\n")
        else:
            write_stdout((f"[Failed to fetch product info: {response.get('msg','unknown error')}]\r\n").encode())
        sys.exit(0)

    if args.command == "save-config":
        msg = {"op": "save-config"}
        ok, err = await send_config_update(args.host, args.port, msg, expected_op="save-config")
        if not ok:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "config-port":
        msg = {"op": "config_port", "line": args.line}
        if args.baudrate is not None:
            msg["baudrate"] = args.baudrate
        if args.databits is not None:
            msg["databits"] = args.databits
        if args.parity is not None:
            msg["parity"] = args.parity
        if args.stopbits is not None:
            msg["stopbits"] = args.stopbits
        if args.flowcontrol is not None:
            msg["flowcontrol"] = args.flowcontrol
        ok, err = await send_config_update(args.host, args.port, msg, expected_op="config_port")
        if not ok:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "config-op":
        msg = {"op": "config_op", "line": args.line}
        if args.mode is not None:
            msg["mode"] = args.mode
        if args.max_clients is not None:
            msg["max_clients"] = args.max_clients
        if args.idle_timeout is not None:
            msg["idle_timeout"] = args.idle_timeout
        if args.label is not None:
            msg["label"] = args.label
        ok, err = await send_config_update(args.host, args.port, msg, expected_op="config_op")
        if not ok:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "config-user":
        msg = {"op": "config_user", "username": args.username}
        if args.role is not None:
            msg["role"] = args.role
        if args.groups is not None:
            msg["groups"] = args.groups.split(',')
        if args.password is not None:
            msg["password"] = args.password

        # Send to server
        success, err = await send_config_update(args.host, args.port, msg, expected_op="config_user")
        print(f"Server update {'succeeded' if success else 'failed'} for user {args.username}.")
        if not success:
            eprint(f"Error: {err}")
            sys.exit(1)

        # If the server update is successful and a password is provided, create the system user
        if success and args.password is not None:
            try:
                subprocess.run([
                    "sudo", "/usr/local/bin/setup_ssh_dispatch.py",
                    "--create-users", "--users", args.username,
                    "--password", args.password,
                    "--quiet"
                ], check=True)
            except subprocess.CalledProcessError as e:
                eprint(f"Local user sync failed for {args.username}: {e}")
                # Optionally, send a command to revert the config change on the server
                # This would require a "revert" or "delete" operation to be implemented
                sys.exit(1)
        return

    if args.command == "config-no-user":
        msg = {"op": "config_no_user", "username": args.username}

        # First, try to update the config on the server
        success, err = await send_config_update(args.host, args.port, msg, expected_op="config_no_user")

        # If the server update is successful, delete the system user
        if success:
            try:
                subprocess.run([
                    "sudo", "/usr/local/bin/setup_ssh_dispatch.py",
                    "--delete-users", args.username,
                    "--remove-home",
                    "--quiet"
                ], check=True)
            except subprocess.CalledProcessError as e:
                eprint(f"Local user delete failed for {args.username}: {e}")
                # Potentially revert the server config change here
                sys.exit(1)
        else:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "config-group":
        msg = {"op": "config_group", "groupname": args.groupname}
        if args.ports is not None:
            # Convert port strings to integers
            try:
                msg["ports"] = [int(p.strip()) for p in args.ports.split(',')]
            except ValueError:
                eprint("Error: Port list must contain only numbers.")
                sys.exit(1)
        if args.role is not None:
            msg["role"] = args.role
        ok, err = await send_config_update(args.host, args.port, msg, expected_op="config_group")
        if not ok:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "config-no-group":
        msg = {"op": "config_no_group", "groupname": args.groupname}
        ok, err = await send_config_update(args.host, args.port, msg, expected_op="config_no_group")
        if not ok:
            eprint(f"Error: {err}")
            sys.exit(1)
        return

    if args.command == "user-role":
        # Fetch config from the running server (like print_config_from_server)
        reader, writer = await asyncio.open_connection(args.host, args.port)
        writer.write(json.dumps({"op": "config"}).encode() + b"\n")
        await writer.drain()
        line = await reader.readline()
        try:
            msg = json.loads(line.decode())
        except Exception:
            msg = {"op": "error", "msg": "invalid response"}
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        if msg.get("op") != "config":
            write_stdout((f"[Failed to fetch config: {msg.get('msg','unknown error')}]\n").encode())
            sys.exit(1)
        config = msg.get("config", {})
        # Compute effective role for the user (inline logic from server.py)
        ROLE_PRIORITY = ["admin", "console_user", "operator", "none"]
        def get_effective_role(username, config):
            users = config.get("users", {})
            groups = config.get("groups", {})
            user = users.get(username)
            if not user:
                return None
            user_role = user.get("role")
            # "none" means no user-specific override; inherit from groups.
            if user_role and user_role != "none":
                return user_role
            user_groups = user.get("groups", [])
            group_roles = [groups[g].get("role") for g in user_groups if g in groups and groups[g].get("role")]
            if not group_roles:
                return None
            group_roles_set = set(group_roles)
            for role in ROLE_PRIORITY:
                if role in group_roles_set:
                    return role
            return group_roles[0] if group_roles else None
        role = get_effective_role(args.username, config)
        if role is None:
            write_stdout(f"[No role found for user: {args.username}]\n".encode())
            sys.exit(1)
        write_stdout((role + "\n").encode())
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
