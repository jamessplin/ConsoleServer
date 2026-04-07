# seriald (demo)

A minimal asyncio serial daemon that arbitrates a single writer per line and broadcasts output to all attached clients.

- Server: tools/seriald/server.py (listens on 127.0.0.1:25001)
- Client: tools/seriald/client.py (bridges stdin/stdout to a line)
- Backend: FakeSerialDevice (for demo). Swap to pyserial for real /dev/tty* or RFC2217 via ser2net.

## Run

```bash
# Terminal 1: start the daemon
python3 tools/seriald/server.py --config tools/seriald/config.json

# Terminal 2: connect as writer
python3 tools/seriald/client.py --line 1

# Terminal 3: connect as observer
python3 tools/seriald/client.py --line 1 --observer
```

Type `exit` in the client to detach.

Client commands
- `exit`: detach from the current line.
- `override`: request writer role in exclusive mode (demotes the previous writer and places them at the front of the promotion queue).

### Shared mode demo

You can run a shared-writer demo on a separate line (e.g., line 2) when configured for `shared` mode. In shared mode, multiple writers can attach; a micro-lock grants a short write window to the writer who starts typing first and releases on newline or timeout (`window_ms`).

```bash
# Terminal 1: start the daemon (if not already)
python3 tools/seriald/server.py --config tools/seriald/config.json

# Terminal 2: writer A attaches to shared line 2
python3 tools/seriald/client.py --line 2

# Terminal 3: writer B also attaches to shared line 2
python3 tools/seriald/client.py --line 2

# Optional: Terminal 4 as observer on line 2
python3 tools/seriald/client.py --line 2 --observer
```

Tips:
- Start typing in one writer, press Enter to release the write window.
- The other writer can then type within their own window or after timeout (`window_ms`).
- Observers see device output and writer keystrokes when `echo` is enabled.

Note on configuration: set per-line mode in `tools/seriald/config.json` under `lines.{id}.mode` to `exclusive` or `shared`, and adjust `window_ms`/`echo` as needed. Restart the daemon after edits. See Per-port configuration below for details.

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

Install system-wide client/CLI (recommended):

```bash
sudo ./tools/seriald/install_helpers.sh
```

Manual install (alternative):

```bash
# Install seriald client and console CLI into /usr/local/bin
sudo install -m 0755 tools/seriald/client.py /usr/local/bin/seriald-client
sudo install -m 0755 tools/seriald/console_cli.py /usr/local/bin/console-cli

# Quick check
command -v seriald-client console-cli
```

List daemon sessions (writer/observers per line):

```bash
seriald-status      # requires seriald running (default 127.0.0.1:25001)
```

If usernames show as "unknown":

- Reinstall helpers to ensure the client sends the username, then reconnect:
    ```bash
    sudo ./tools/seriald/install_helpers.sh
    # restart or detach any existing client sessions, then re-attach
    ```
- The client derives the username from `$SSH_USER`, `$LOGNAME`, `$USER`, or the system login name; if all are missing in your SSH environment, the daemon will print `unknown`.
- You can verify the installed client is updated by checking it includes `"user"` in the attach payload:
    ```bash
    grep -n '"user"' /usr/local/bin/seriald-client || true
    ```
- As an alternative quick check, run the repo client directly (always up to date):
    ```bash
    python3 tools/seriald/client.py --line 1
    seriald-status
    ```

Tip: From the Console Server CLI (port 22), `show sessions` also prints daemon sessions if `seriald-status` is available in the system path.

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

### Per-user dual-mode mapping (final)

If you want one user (e.g., `bob`) to land in the Console Server CLI on the normal SSH port (22) but attach directly to a specific serial line when using an alternate port (e.g., 20001), add both `Match` blocks. This keeps `bob`'s login shell as a normal POSIX shell (e.g., `/bin/bash`) and relies on `ForceCommand` per port.

```
Port 22
Port 20001

# 1) Port 22 → Console Server CLI
Match User bob LocalPort 22
    ForceCommand /usr/local/bin/console-cli
    PermitTTY yes

# 2) Ports 20001–20024 → Direct attach via dispatch
# Single wrapper computes --line from target port
Match User bob LocalPort 2000*,2001*,2002*
    ForceCommand /usr/local/bin/console-ssh-dispatch
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
```

Reload and verify:

```bash
sudo systemctl reload sshd

# Verify effective config for each port
sudo sshd -T -C user=bob -C lport=22    | egrep 'forcecommand|permittty'
sudo sshd -T -C user=bob -C lport=20001 | egrep 'forcecommand|permittty'
sudo sshd -T -C user=bob -C lport=20024 | egrep 'forcecommand|permittty'

# Test
ssh -p 22 bob@<host>      # Expect Console Server CLI
ssh -p 20001 bob@<host>   # Expect seriald client attach (no PTY)
ssh -p 20024 bob@<host>   # Expect seriald client attach (no PTY)
```

Notes:
- Ensure `bob`'s login shell in `/etc/passwd` is a real shell (e.g., `/bin/bash`). Do not set it to `console-cli`; the `Match` + `ForceCommand` above controls behavior per port.
- Install the client/CLI to system paths as shown below so `sshd` can execute them without homedir traversal issues.

#### Wrapper variant (robust fallback)

On systems where the user's login shell is non-standard or ForceCommand is inconsistently applied, wrap the command with `/bin/sh -c` to ensure execution via a POSIX shell:

```
Match User bob LocalPort 20001
    ForceCommand /bin/sh -c '/usr/bin/python3 /usr/local/bin/seriald-client --line 1'
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
```

### Install the dispatch wrapper

Install and set permissions:

```bash
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch
```

This wrapper derives the line number from the SSH server port (22 → CLI; 20001–20024 → `--line 1..24`). It avoids adding 24 separate `Match` entries.

### Optional: generate sshd drop-in config

Use the helper to install the wrapper and write an sshd drop-in with explicit port list and `Match` rules for a user (default: `bob`):

```bash
sudo tools/seriald/install_ssh_dispatch.sh -u bob -s 20001 -e 20024

# Inspect and reload
sudo cat /etc/ssh/sshd_config.d/console-seriald.conf
sudo systemctl reload sshd
```

Dry-run or print-only:

```bash
# Show actions without executing
sudo tools/seriald/install_ssh_dispatch.sh -u bob -s 20001 -e 20024 -d

# Print the generated config to stdout (no write)
sudo tools/seriald/install_ssh_dispatch.sh -u bob -s 20001 -e 20024 -n
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
    PermitTTY no
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

The daemon now supports real serial devices and ser2net out of the box via `pyserial`.

- Local device: set `device` and optional `baud` in `tools/seriald/config.json`.
- ser2net (RFC2217): set `url` to `rfc2217://<host>:<port>` and optional `baud`.

Example `tools/seriald/config.json`:

```
{
    "listen": {"host": "127.0.0.1", "port": 25001},
    "lines": {
        "1": {"mode": "exclusive", "echo": true, "window_ms": 800,
               "device": "/dev/ttyS0", "baud": 115200},
        "2": {"mode": "shared", "echo": true, "window_ms": 800,
               "url": "rfc2217://127.0.0.1:2001", "baud": 115200}
    }
}
```

Install dependency (already listed in project requirements):

```bash
pip install pyserial
```

### ser2net setup (RFC2217)

ser2net 4.x YAML example to expose `/dev/ttyUSB0` on TCP 2001 with RFC2217:

```yaml
# /etc/ser2net.yaml
connection: &line1
  accepter: telnet(rfc2217),2001
  connector: serialdev,/dev/ttyUSB0,115200n81,local
  options:
    kickolduser: true
```

Then point the daemon to it using an RFC2217 URL:

```
"lines": {
  "2": {"mode": "exclusive", "echo": true, "window_ms": 800,
         "url": "rfc2217://127.0.0.1:2001", "baud": 115200}
}
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
        "1": {"mode": "exclusive", "echo": true, "window_ms": 800},
        "2": {"mode": "shared", "echo": true, "window_ms": 800}
    }
}
```

- `mode`: `exclusive` enforces a single writer; `shared` allows multiple clients to attempt writes, gated by a micro-lock.
- `echo`: when true, broadcast writer keystrokes to observers.
- `window_ms`: shared-mode lock window for a writer to complete a line; released on newline or timeout.

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
