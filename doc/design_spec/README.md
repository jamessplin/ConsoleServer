# seriald

An asyncio-based serial daemon that arbitrates a single writer per line (exclusive) or coordinated shared writes, and broadcasts device output to all attached clients.

## Prerequisites

On Debian-based systems (like Ubuntu), install the required packages using `apt`:

```bash
sudo apt-get update
sudo apt-get install python3-click python3-serial python3-passlib ser2net
```

## Installation and Management

### 1. SSH Port Setup

First, run the `setup_ssh_dispatch.py` script to configure the SSH ports that will be used to connect to the serial lines. This only needs to be done once.

```bash
# Example: Expose ports 20001 through 20012 for IPv4 connections
sudo tools/seriald/setup_ssh_dispatch.py -s 20001 -e 20012 --address-family inet
```

For larger port ranges that may exceed OpenSSH's listener limit, you can enable a secondary `sshd` instance:
```bash
# Example: Split ports 20001-20024 across two sshd instances
sudo tools/seriald/setup_ssh_dispatch.py -s 20001 -e 20024 \
    --address-family inet \
    --enable-second-sshd \
    --second-sshd-config /etc/ssh/sshd_config_seriald2 \
    --second-sshd-service ssh-seriald2.service
```

### 2. Install and Start the `seriald` Service

The recommended way to install the client tools and the `seriald` service is to use the `install_helpers.sh` script. This will install all components, enable the service to start on boot, and start it immediately.

```bash
sudo ./tools/seriald/install_helpers.sh
```

### 3. Managing the Service

Once installed, you can manage the `seriald` service using standard `systemctl` commands:

```bash
# Check the status and view recent logs
sudo systemctl status seriald.service

# Stop the service
sudo systemctl stop seriald.service

# Start the service manually
sudo systemctl start seriald.service

# Restart the service (e.g., after changing config.json)
sudo systemctl restart seriald.service
```

## User Management

### Remove all seriald-related users, groups, configs, and services (full uninstall)

```bash
sudo tools/seriald/setup_ssh_dispatch.py --remove-all
```

This will:
- Remove all users in the 'console' group
- Remove the 'console' group
- Remove all seriald-related SSH/systemd configs and dispatch wrapper from system folders
- Reload systemd and sshd
- Supports `--dry-run` to preview actions without making changes

### Add a user named 'alice'

```bash
sudo tools/seriald/setup_ssh_dispatch.py --create-users --users alice --password <your_password>
```

### Delete a user named 'alice'

```bash
sudo tools/seriald/setup_ssh_dispatch.py --delete-users alice --remove-home
```

Notes:
- The script will automatically create the 'console' group if it does not exist before adding users.
- The `--password` option is required for setting the user's password. If omitted, the account is locked.
- Use `--dry-run` to preview actions without making changes.

## Configuration

The server is configured via `tools/seriald/config.json`. The service must be restarted for changes to take effect.

```bash
sudo systemctl restart seriald.service
```


Explanation:
- --print-only: prints the generated sshd drop-in to stdout and skips writing it. It still runs user/group actions unless combined with `--no-install-dispatch` and `--no-fix-include` to avoid side effects.
- --dry-run: simulates all actions (user/group, installs, writes, reloads) without executing them, printing the commands instead.

Notes:
- Port 22 is group-based: members of `console` land in `console-cli`.
- Direct-attach ports are mapped via the dispatch wrapper (no user needed).
- The tool reloads `sshd` unless `--no-reload` is passed.


Install system-wide client/CLI (recommended):

```bash
sudo ./tools/seriald/install_helpers.sh
```


Manual install (alternative):

```bash
# Install seriald client, console CLI, and status tool into /usr/local/bin
sudo install -m 0755 tools/seriald/client.py /usr/local/bin/seriald-client
sudo install -m 0755 tools/seriald/console_cli.py /usr/local/bin/console-cli
sudo install -m 0755 tools/seriald/status.py /usr/local/bin/seriald-status
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch


# Quick check
command -v seriald-client console-cli seriald-status
```

## Generating Per-Port ser2net YAML Configs

To generate individual ser2net YAML files (cs1.yaml to csN.yaml) for each serial port:

1. Run the script from the project root:

    python3 tools/seriald/gen_ser2net_cfg.py [base_port] [num_ports]

    - base_port: (optional) Starting TCP port number (default: 50000)
    - num_ports: (optional) Number of ports/files to generate (default: 24)

2. The files will be created in:

    tools/seriald/ser2net_cfg/

Each file is named csN.yaml (where N is 1 to num_ports) and is configured for a unique TCP port and serial device (e.g., ttyUSB0 for cs1.yaml, ttyUSB23 for cs24.yaml).

Debug messages will be printed for folder and file creation.

### Console CLI Usage (Click version)

The `console-cli` tool now uses the [Click](https://click.palletsprojects.com/) library for a modern command-based interface. Run `console-cli --help` to see available commands:

```
Usage: console-cli [OPTIONS] COMMAND [ARGS]...

    Console Server CLI (Click version)

Options:
    --help  Show this message and exit.

Commands:
    exit           Exit the CLI.
    open-line      Open a line locally (demo backend).
    override       Override writer for a line (admin only).
    sd             Attach to a serial line via seriald-client.
    shell          Switch to host shell.
    show-config    Show the config from the running seriald server.
    show-sessions  Show local and daemon sessions.
```

Example usage:

```
# Attach to line 1 via seriald-client
console-cli sd 1

# Attach as observer
console-cli sd 1 --observer

# Open a local demo line
console-cli open-line 1

# Show sessions
console-cli show-sessions

# Show config
console-cli show-config

# Switch to host shell
console-cli shell

# Exit
console-cli exit
```

## 1) Configure the Server

Edit [tools/seriald/config.json](config.json). Minimal example:

```
{
    "listen": {"host": "127.0.0.1", "port": 25001},
    "keepalive_ms": 10000,
    "lines": {
        "1": {"mode": "exclusive", "echo": true, : 800, "max_clients": 2, "idle_timeout": 600},
        "2": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600},
        "3": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 30},
        "23": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": null, "idle_timeout": 600},
        "24": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 1, "idle_timeout": 600},
        "25": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600},
        "26": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600}
    }
}
```


## Role-Based Access Control (RBAC)

seriald supports role-based access control (RBAC) for port access using a users/groups model defined in `config.json`.

- **users**: An object keyed by username, each entry containing:
        - `password`: (if used for local auth)
        - `groups`: list of group names the user belongs to
        - `role`: informational (e.g., "admin", "operator")
- **groups**: An object keyed by group name, each entry containing:
        - `port_list`: list of allowed port (line) numbers for the group
        - `role`: informational

Example config excerpt:

```json
{
    "groups": {
        "Group_A": { "port_list": [1,2,3,4], "role": "operator" },
        "Group_B": { "port_list": [5,6,7,8], "role": "console_user" }
    },
    "users": {
        "alice": { "password": "changeme1", "groups": ["Group_A"], "role": "operator" },
        "bob":   { "password": "changeme2", "groups": ["Group_B"], "role": "admin" },
        "ted":   { "password": "changeme2", "groups": ["Group_A", "Group_B"], "role": "admin" }
    }
}
```

### Port Access Enforcement

When a client requests to attach to a line, the server checks the user's group memberships and only allows access if the requested line is in the union of all `port_list` entries for the user's groups. If not, the attach is denied with an error.

This logic is enforced in the server and applies to all attach operations, regardless of how the client is launched (direct, CLI, or via SSH dispatch).

### Example attach flow

1. User connects and requests to attach to line 2 as "alice".
2. Server looks up `users["alice"]`, finds group `Group_A`.
3. Server checks `groups["Group_A"].port_list` and allows attach if 2 is present.
4. If not present, attach is denied.

See the `config.json` and server.py for details.

## Configuration Parameters

- `listen`: Object with `host` and `port` for the server to bind.
- `keepalive_ms`: *(optional, default: 15000)* Interval in milliseconds for server-to-client keepalive pings. The server sends a lightweight ping to each client at this interval to detect and prune dead connections. Lower values detect failures faster; higher values reduce network traffic.
- `lines`: Object mapping line numbers to per-line configuration (see below).

### Example

```
{
    "listen": {"host": "127.0.0.1", "port": 25001},
    "keepalive_ms": 10000,
    "lines": {
        "1": {"mode": "exclusive", "echo": true, "window_ms": 800},
        "2": {"mode": "shared",    "echo": true, "window_ms": 800}
    }
}
```

- `mode`: `exclusive` enforces a single writer; `shared` allows multiple clients to attempt writes, gated by a micro-lock.
- `echo`: when true, broadcast writer keystrokes to observers.
- `window_ms`: shared-mode lock window for a writer to complete a line; released on newline or timeout.
- `max_clients`: maximum number of clients allowed to attach to this line (null for unlimited).
- `idle_timeout`: disconnect clients after this many seconds of inactivity (per-line, optional).

Real devices and RFC2217 (ser2net) are supported via `pyserial`:

```
{
    "listen": {"host": "127.0.0.1", "port": 25001},
    "lines": {
        "1": {"mode": "exclusive", "echo": true, "window_ms": 800,
               "device": "/dev/ttyS0", "baud": 115200},
        "2": {"mode": "shared",    "echo": true, "window_ms": 800,
               "url": "rfc2217://127.0.0.1:2001", "baud": 115200}
    }
}
```

Install dependency (if not installed):

```bash
pip install pyserial
```

## 2) Run the Server (Systemd Service)

The recommended way to run the `seriald` server is as a `systemd` service. This ensures it starts automatically on boot and is managed correctly.

### One-Time Service Installation

First, you must install the `systemd` unit file. This only needs to be done once. The `seriald.service` file is included in this directory.

```bash
# Move the service file to the systemd directory
sudo mv /home/bmc/james/git/diag_console/tools/seriald/seriald.service /etc/systemd/system/seriald.service

# Reload the systemd daemon to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable seriald.service
```

### Managing the Service

Once installed, you can control the `seriald` service with standard `systemctl` commands.

**Starting the Server:**
The service will start automatically on the next boot. To start it immediately after installation, run:
```bash
sudo systemctl start seriald.service
```

**Stopping the Server:**
To stop the service gracefully:
```bash
sudo systemctl stop seriald.service
```

**Checking the Status:**
To see the current status, view recent logs, and check for errors:
```bash
sudo systemctl status seriald.service
```

## 3) Client Access

Attach as writer (exclusive/shared):

```bash
python3 tools/seriald/client.py --line 1
```

Attach as observer:

```bash
python3 tools/seriald/client.py --line 1 --observer
```

Client commands
- `exit`: detach from the current line.
- `override`: request writer role in exclusive mode (demotes existing writer and places them at the front of the promotion queue).

### Shared mode quick demo

```bash
# Writer A on shared line 2
python3 tools/seriald/client.py --line 2

# Writer B also on shared line 2
python3 tools/seriald/client.py --line 2

# Optional observer
python3 tools/seriald/client.py --line 2 --observer
```

Tips:
- Start typing in one writer, press Enter to release the write window.
- The other writer gets the next window or after `window_ms` timeout.
- Observers see device output and writer keystrokes when `echo` is enabled.

## SSH mapping (direct access)

Add to /etc/ssh/sshd_config:

```
Port 22
Port 20001
Match LocalPort 20001
    ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
```

Reload sshd:

```bash
sudo systemctl reload sshd
```

Then bridge directly:

```bash
ssh -p 20001 <host>
```

## Sessions

sd line 1              # attach as writer to line 1 via seriald

## Session IP/Port Workaround for SSH Forced Commands

When using SSH forced commands or dispatch scripts, the seriald-client is launched on the server, so the server sees the connection as coming from localhost (127.0.0.1). To show the real remote client IP/port in session lists, a workaround is used:

- The dispatch wrapper (console-ssh-dispatch.sh) parses `$SSH_CONNECTION` and exports `SSH_CLIENT_IP` and `SSH_CLIENT_PORT` as environment variables before launching seriald-client.
- seriald-client (client.py) reads these variables and includes them in the attach message sent to the server.
- The server (server.py) uses these fields for session reporting if provided, so the session list shows the true remote client address.

This allows administrators to see where clients are connecting from, even when the client is launched locally on the server via SSH forced command.

Example:

```bash
export SSH_CLIENT_IP="192.168.1.100"
export SSH_CLIENT_PORT="54321"
python3 tools/seriald/client.py --line 1
```

The session list will show `ip=192.168.1.100 port=54321` for this client.

List current lines, writer, and observers:

```bash
# Using the repo helper
python3 tools/seriald/status.py

# Or, if installed system-wide via helpers
seriald-status
```

If usernames show as "unknown", ensure the system client is installed via helpers and reconnect:

```bash
sudo ./tools/seriald/install_helpers.sh
```

The client derives the username from `$SSH_USER`, `$LOGNAME`, `$USER`, or the system login name.

Why sessions can linger
- Abruptly closing the SSH window can leave the `seriald-client` process orphaned briefly; its TCP connection to the daemon remains open until the OS or client exits.
- The daemon removes clients immediately on `detach`, EOF from the client, or any write error. If no traffic occurs, a silent zombie can briefly appear in status.
- Mitigation: the daemon sends periodic keepalive pings and prunes broken connections automatically. You can also manually check and terminate stray clients:
    - List clients: `ps -ef | grep seriald-client | grep -v grep`
    - Kill by PID: `sudo kill -TERM <pid>`

### From the Console Server CLI (port 22), `show sessions` also prints daemon sessions if `seriald-status` is available in the system path.

### From CLI (port 22) to seriald

If you connect on port 22 and land in the Console Server CLI, you can still attach to the daemon so that `exclusive`/`shared` arbitration applies.

Requirements:
- `seriald` is running (127.0.0.1:25001 by default)
- System client installed at `/usr/local/bin/seriald-client`

Steps:
```bash
ssh bob@<host>
# At the CLI prompt:
sd line 1              # attach as writer to line 1 via seriald
sd line 1 --observer   # attach as observer
```

Tip: type `exit` in the client to detach and return to the CLI prompt.

### Dual-mode mapping (final)

If you want users to land in the Console Server CLI on the normal SSH port (22) but attach directly to a specific serial line when using alternate ports (e.g., 20001), add both `Match` blocks. This keeps users' login shells as normal POSIX shells (e.g., `/bin/bash`) and relies on `ForceCommand` per port.

```
Port 22
Port 20001

# 1) Port 22 → Console Server CLI (group-based)
# Only members of the group land in the CLI; others get normal shell
Match Group console LocalPort 22
    ForceCommand /usr/local/bin/console-cli
    PermitTTY yes

# 2) Ports 20001–20012 → Direct attach via dispatch (all users)
# Single wrapper computes --line from target port
Match LocalPort 20001
    ForceCommand /usr/local/bin/console-ssh-dispatch
    PermitTTY yes
    AllowTcpForwarding no
    X11Forwarding no
Match LocalPort 20002
    ForceCommand /usr/local/bin/console-ssh-dispatch
    PermitTTY yes
    AllowTcpForwarding no
    X11Forwarding no
...
```

Reload and verify:

```bash
sudo systemctl reload sshd

sudo sshd -T -C lport=22    | egrep 'forcecommand|permittty|addressfamily'
sudo sshd -T -C lport=20001 | egrep 'forcecommand|permittty|addressfamily'

# Test
ssh -p 22 bob@<host>      # Expect Console Server CLI (if in console group)
ssh -p 20001 bob@<host>   # Expect seriald client attach
ssh -p 20012 bob@<host>   # Expect seriald client attach
```

Notes:
- Install the client/CLI to system paths as shown below so `sshd` can execute them without homedir traversal issues.

#### Wrapper variant (robust fallback)

On systems where ForceCommand needs a shell wrapper, use `/bin/sh -c` to ensure execution via a POSIX shell:

```
Match LocalPort 20001
    ForceCommand /bin/sh -c '/usr/bin/python3 /usr/local/bin/seriald-client --line 1'
    PermitTTY yes
    AllowTcpForwarding no
    X11Forwarding no
```


### SSH_CONNECTION environment variable

The dispatch wrapper script ([console-ssh-dispatch.sh](console-ssh-dispatch.sh)) relies on the SSH-provided environment variable `$SSH_CONNECTION` to determine connection details for each session. This variable is set by OpenSSH for every session and contains four space-separated fields:

    <client IP> <client port> <server IP> <server port>

For example:

    192.168.1.100 54321 192.168.1.10 20001

The script parses `$SSH_CONNECTION` to extract the server port, which is then used to determine the target serial line or CLI mode. If `$SSH_CONNECTION` is not set, the script exits with an error. For more details, see the "ENVIRONMENT VARIABLES" section of the `ssh` manual (`man ssh`).

### Install the dispatch wrapper

Install and set permissions:

```bash
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch
```

This wrapper derives the line number from the SSH server port (22 → CLI; 20001–20012 → `--line 1..12`). You still need per‑port `Match LocalPort` blocks; the wrapper simply computes the correct `--line` from the target port.

### Optional: generate sshd drop-in config

Use the helper to install the wrapper and write an sshd drop-in with explicit port list and per-port `Match` rules (all users for direct-attach). For large ranges, prefer IPv4-only:

```bash
sudo tools/seriald/setup_ssh_dispatch.py -s 20001 -e 20012 --address-family inet

# Inspect and reload
sudo cat /etc/ssh/sshd_config.d/console-seriald.conf
sudo systemctl reload sshd
```

Dry-run or print-only:

```bash
# Show config without writing
sudo tools/seriald/setup_ssh_dispatch.py -s 20001 -e 20012 --address-family inet --print-only
```
# Shell helper (IPv4-only example via manual edit)
```bash
sudo tools/seriald/install_ssh_dispatch.sh -s 20001 -e 20012
sudo sed -i '1i AddressFamily inet' /etc/ssh/sshd_config.d/console-seriald.conf
sudo systemctl reload sshd
```

### Troubleshooting (SSH ForceCommand)

If connecting on the mapped port still lands you in `Console Server CLI`, the `Match LocalPort` block likely didn’t apply.

- Verify the effective config for the port:
    ```bash
    # Check that ForceCommand applies for local port 20001 and your user
    sudo sshd -T -C lport=20001 -C user=$USER -C addr=127.0.0.1 | egrep 'forcecommand|permittty|passwordauthentication|pubkeyauthentication|allowgroups'
    # If your sshd version doesn't support lport, try:
    sudo sshd -T -C port=20001 -C user=$USER -C addr=127.0.0.1 | egrep 'forcecommand|permittty|passwordauthentication|pubkeyauthentication|allowgroups'
    ```
- Ensure the `Match LocalPort 20001` block appears after any other `Match` blocks and after included files (e.g., `/etc/ssh/sshd_config.d/*.conf`).
- Confirm the path exists and is readable:
    ```bash
    ls -l /usr/bin/python3 /usr/local/bin/seriald-client
    ```
- If your user’s login shell is set to `console-cli` (demo), ForceCommand should still override, but if not:
    ```bash
    getent passwd $USER
    # Temporarily set shell to /bin/bash to test
    sudo chsh -s /bin/bash $USER
    sudo systemctl reload sshd
    ```
    Alternatively, use the wrapper variant in the config:
    ```
    Match LocalPort 20001
        ForceCommand /bin/sh -c '/usr/bin/python3 /usr/local/bin/seriald-client --line 1'
        PermitTTY no
    ```
- Check SSH logs for hints:
    ```bash
    journalctl -u ssh -n 100 --no-pager
    ```

Expected connection messages:
- `PTY allocation request failed on channel 0` is normal when `PermitTTY no` is set for the ForceCommand port.
- On success, you should see the client banner and attach status, not `Console Server CLI`.

### Authentication & Access Control

By default, SSH will prompt for a password unless the user has a valid public key installed. You can enforce keys-only or allow passwords per daemon port.

Keys-only (recommended)

```bash
# /etc/ssh/sshd_config
Port 22
Port 20001

Match LocalPort 20001
    ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
```

Allow passwords (if desired)

```bash
# /etc/ssh/sshd_config
Port 22
Port 20001

Match LocalPort 20001
    ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1
    PermitTTY no
    PubkeyAuthentication yes
    PasswordAuthentication yes
    KbdInteractiveAuthentication yes
```

Restrict who can use the port (optional)

```bash
# /etc/ssh/sshd_config
Match LocalPort 20001
    AllowGroups console
    ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1
    PermitTTY yes
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
```

Group setup and keys installation

```bash
# Create/ensure group and add users
sudo groupadd -f console
sudo usermod -aG console bob
sudo usermod -aG console alice

# Install user SSH key (run via normal SSH port, not forced client port)
ssh-copy-id bob@<host>

# Reload SSH daemon
sudo systemctl reload sshd
```

## Using a real serial port or ser2net (RFC2217)

The daemon supports real serial devices and ser2net via `pyserial`.

- Local device: set `device` and optional `baud` in `tools/seriald/config.json`.
- ser2net (RFC2217): set `url` to `rfc2217://<host>:<port>` and optional `baud`.

### ser2net setup (RFC2217)

ser2net 4.x YAML example to expose `/dev/ttyUSB0` on TCP 2001 with RFC2217:

```yaml
# /etc/ser2net.yaml
%YAML 1.1
---
define: &banner \r\nser2net port \p device \d [\B]\r\n\r\n
connection: &com1_rfc2217
    accepter: telnet(rfc2217),2001
    enable: on
    options:
        banner: *banner
        kickolduser: true
        telnet-brk-on-sync: true
    connector: serialdev,/dev/ttyUSB0,115200n81,local
```


Notes:
- RFC2217 lets pyserial negotiate line settings; still pass `baud` for clarity.
- If you prefer raw TCP in ser2net, switch its `accepter` to `tcp,PORT` and use `pyserial` with a raw socket URL, or keep RFC2217 for best compatibility.

## Per-port configuration

Edit `tools/seriald/config.json`:

```
{
    "listen": {"host": "127.0.0.1", "port": 25001},
    "lines": {
        "1": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600},
        "2": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600},
        "3": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 30},
        "23": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": null, "idle_timeout": 600},
        "24": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 1, "idle_timeout": 600},
        "25": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600},
        "26": {"mode": "shared", "echo": true, "window_ms": 800, "max_clients": 2, "idle_timeout": 600}
    }
}
```

- `mode`: `exclusive` enforces a single writer; `shared` allows multiple clients to attempt writes, gated by a micro-lock.
- `echo`: when true, broadcast writer keystrokes to observers.
- `window_ms`: shared-mode lock window for a writer to complete a line; released on newline or timeout.
- `max_clients`: maximum number of clients allowed to attach to this line (null for unlimited).
- `idle_timeout`: disconnect clients after this many seconds of inactivity (per-line, optional).

## Relationship to console_cli.py

- Purpose: the original CLI at [tools/seriald/console_cli.py](console_cli.py) is a single-process demo that starts a fake serial backend inside the same process each time a user logs in. It shows roles and a basic attach flow (`open line 1`) but each SSH session is isolated, so writer arbitration isn’t shared across users.
- This daemon: [tools/seriald/server.py](server.py) centralizes the serial line(s) into one process and arbitrates a single writer (exclusive) or coordinated shared writes (shared). All clients attached to the same line see the same device output.
- Client vs CLI: [tools/seriald/client.py](client.py) replaces the ad‑hoc attach in the CLI. Instead of `open line 1`, the client connects to the daemon and requests writer/observer. You can still keep the CLI for demos while using the daemon for multi-user coordination.
- SSH integration choices:
    - CLI-as-shell: keep users landing in [tools/seriald/console_cli.py](console_cli.py) for the original demo experience.
    - Daemon-backed direct access: use `sshd` `Match LocalPort` with `ForceCommand` to launch [tools/seriald/client.py](client.py) per port (e.g., 20001 → line 1) so users `ssh -p 20001 host` attach directly. Authentication remains SSH; the daemon handles writer policy.
    - CLI → seriald: from the CLI on port 22, use `sd line <n> [--observer]` to attach through the daemon, enabling shared/exclusive arbitration without changing your port-22 mapping.
- Migration tip: start with the daemon for any multi-user/port-scalable setup. Keep the CLI available for local development and quick demonstrations where per-session isolation is acceptable.

### Device CLI shell (console_cli.py)

- In device mode within the CLI, type `shell` to open a host shell.
- To return from the host shell back to the device session, type `exit` or press `Ctrl-D`.
- To detach from the device back to the CLI, type `exit` at the device prompt.

## Writer Promotion (exclusive mode)

When the active writer disconnects or detaches in `exclusive` mode, the server automatically promotes the earliest observer on that line to become the new writer.

- Trigger: writer leaves (detach or connection drop).
- Order: FIFO by attach time. The first observer who joined after the writer is promoted first.
- Scope: only in `exclusive` mode. Shared mode is unaffected.
- Notification: the promoted client receives a `role` message; the sample client prints `[Promoted to writer]`.
- Overrides: using `override` demotes the previous writer and places them at the front of the queue for the next promotion.
- Cleanup: observers that detach are removed from the queue.

Quick test

```bash
# Start daemon
python3 tools/seriald/server.py --config tools/seriald/config.json

# Writer attaches
python3 tools/seriald/client.py --line 1

# Observer A attaches (queued)
python3 tools/seriald/client.py --line 1 --observer

# Observer B attaches (queued)
python3 tools/seriald/client.py --line 1 --observer

# In the writer session, type 'exit' to detach.
# Expect: Observer A prints "[Promoted to writer]" and gains write access.
```



## Known Limitations

### Port Number Synchronization

**WARNING:** There is a critical dependency between the SSH dispatch setup script (`setup_ssh_dispatch.py`) and the runtime dispatch wrapper (`console-ssh-dispatch.sh`).

-   `console-ssh-dispatch.sh` contains a **hardcoded base port number (20000)** used to calculate the target serial line from the incoming SSH port (`line=$((SSH_SERVER_PORT - 20000))`).
-   `setup_ssh_dispatch.py` generates the `sshd_config` drop-in with a port range (e.g., 20001-20024).

These two components **must be synchronized**. If you change the port range in `setup_ssh_dispatch.py` to something that does not align with the base port of 20000 in the shell script, the line calculation will be incorrect, and users will be connected to the wrong serial line. The default port range starting from `20001` works correctly with the hardcoded base port.

This will be resolved in a future update by dynamically generating the `console-ssh-dispatch.sh` script to remove the hardcoded value.
