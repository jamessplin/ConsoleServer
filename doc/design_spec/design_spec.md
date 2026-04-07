# Design Spec: SSH Connection Flows

This document describes the two supported SSH entry paths and how sessions are routed: the Console Server CLI on the standard port (22) and direct attach to a serial line via the daemon on an alternate port (20001).

## Overview
- Goal: Provide operators two modes:
  - Port 22 → interactive Console Server CLI
  - Port 20001 → direct attach to seriald line 1
- Implementation: Per-port `sshd` `Match` rules with `ForceCommand` executing either `console-cli` or `seriald-client`.

## Flow 1: Port 22 (CLI Menu)
Command
- `ssh bob@localhost`

Routing
- `sshd` listens on port 22
- `Match User bob LocalPort 22` applies
- `ForceCommand /usr/local/bin/console-cli`
- `PermitTTY yes` (a PTY is allocated)

Sequence (ASCII diagram)
```
[bob:ssh client]
    |
    v
[sshd:22] --(Match User bob, LocalPort 22)--> [ForceCommand console-cli]
    |
    v
[PTY allocated]
    |
    v
[console_cli.py: interactive CLI]
    |
    +--> Menu: device/session options
    |       - open/attach (demo, single-process)
    |       - shell (host shell; exit/Ctrl-D to return)
    |
    +--> Detach: exit back to CLI, then logout
```

Notes
- The CLI is a demo, per-session process; arbitration is not shared across users.
- Keep the user’s login shell as a POSIX shell (e.g., `/bin/bash`); behavior is controlled by `ForceCommand`.

## Flow 2: Port 20001 (Direct Attach)
Command
- `ssh -p 20001 bob@localhost`

Routing
- `sshd` listens on port 20001
- `Match User bob LocalPort 20001` applies
- `ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1`
- `PermitTTY no` (no PTY; you may see: "PTY allocation request failed")

Sequence (ASCII diagram)
```
[bob:ssh client]
    |
    v
[sshd:20001] --(Match User bob, LocalPort 20001)--> [ForceCommand seriald-client --line 1]
    |
    v
[seriald-client] -- TCP(127.0.0.1:25001) --> [seriald server]
    |
    v
[Backend Device] (FakeSerialDevice or real /dev/tty*)
```

Session behavior
- Client banners: "Console Client", "[Connecting to seriald]", "[Attached as writer]" or observer
- Exclusive mode: single writer; observers see output and keystroke echo (if enabled)
- Writer promotion: first observer auto-promoted when writer detaches
- Exit: type `exit` to detach; SSH session ends immediately after detach

## Config Snippets
Port 22 → CLI
```
Match User bob LocalPort 22
    ForceCommand /usr/local/bin/console-cli
    PermitTTY yes
```

Port 20001 → Direct attach
```
Match User bob LocalPort 20001
    ForceCommand /usr/bin/python3 /usr/local/bin/seriald-client --line 1
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
```

Robust fallback (wrapper)
```
Match User bob LocalPort 20001
    ForceCommand /bin/sh -c '/usr/bin/python3 /usr/local/bin/seriald-client --line 1'
    PermitTTY no
```

### Dispatch Wrapper (multi-port mapping)
To avoid writing many `Match` blocks, use a single wrapper that derives the line number from the SSH local port. Port 22 maps to the Console Server CLI; ports 20001–20024 map to lines 1–24 via the `seriald-client`.

Wrapper install:
```
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch
```

`sshd_config` example for one user (`bob`):
```
Port 22
Port 20001
Port 20002
Port 20003
# ... up to desired range (or use a drop-in file)

# Port 22 → Console Server CLI
Match User bob LocalPort 22
    ForceCommand /usr/local/bin/console-ssh-dispatch
    PermitTTY yes

# Ports 20001–20024 → direct attach via dispatch
Match User bob LocalPort 2000*,2001*,2002*
    ForceCommand /usr/local/bin/console-ssh-dispatch
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
```

Behavior:
- 22 → exec `/usr/local/bin/console-cli`
- 20001–20024 → exec `/usr/bin/python3 /usr/local/bin/seriald-client --line <port-20000>`
- Any other port → reject

## Prerequisites
- Install system binaries:
```
sudo ./tools/seriald/install_helpers.sh
```

Manual install (alternative)
```
sudo install -m 0755 tools/seriald/client.py /usr/local/bin/seriald-client
sudo install -m 0755 console_cli.py /usr/local/bin/console-cli
command -v seriald-client console-cli
```
Wrapper install (optional, for multi-port mapping):
```
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch
```
- Start daemon:
```
nohup python3 tools/seriald/server.py --config tools/seriald/config.json >/tmp/seriald.log 2>&1 &
```
- Reload and verify sshd:
```
sudo systemctl reload sshd
sudo sshd -T -C user=bob -C lport=22    | egrep 'forcecommand|permittty'
sudo sshd -T -C user=bob -C lport=20001 | egrep 'forcecommand|permittty'
```

## Expected Outcomes
- Port 22: interactive CLI menu under `console_cli.py`
- Port 20001: direct serial attach via `seriald-client` (no PTY), messages from device streamed live, with arbitration and promotion handled by `seriald`

## CLI → seriald (Port 22)
If you land in the Console Server CLI on port 22, you can still attach through the daemon so shared/exclusive arbitration applies:

Requirements
- `seriald` listening on 127.0.0.1:25001
- `/usr/local/bin/seriald-client` installed

Steps
```
ssh bob@<host>
# at the CLI prompt
sd line 1              # attach as writer to line 1 via seriald
sd line 1 --observer   # attach as observer
```
Type `exit` in the client to detach back to the CLI.

## Modes and PTY
- Exclusive/shared modes are enforced by `seriald` per line (configured in tools/seriald/config.json). They apply to connections via `seriald-client` (e.g., port 20001 or CLI `sd line ...`).
- The standalone `open line 1` path inside the CLI is a demo per-session backend and does not share arbitration across users.
- PTY policy:
    - Port 22 uses `PermitTTY yes` so the CLI and any spawned shells have full interactive terminal features.
    - Port 20001 uses `PermitTTY no` to keep a clean byte stream for serial bridging. If interactive terminal features are required on 20001, enable PTY and set raw mode in a wrapper (e.g., `stty raw -echo; exec ...`).

## Daemon Status and Usernames

The daemon exposes a lightweight status operation to report session state per line (mode, writer, counts, clients).

- Client → Server attach payload now includes `user` so status can show who is connected.
- If the client does not provide a username, status shows `unknown`.
- The provided `seriald-status` utility requests and prints the status.

Usage
```
seriald-status                    # default 127.0.0.1:25001
seriald-status --host 127.0.0.1 --port 25001
```

Example Output
```
Daemon Sessions:
- line 1 [exclusive] : writer=bob (clients=2, writers=1, observers=1)
        - bob role=writer
        - alice role=observer
- line 2 [shared] : writer=none (clients=0, writers=0, observers=0)
```

Username resolution in the client (best effort):
- `$SSH_USER` → `$LOGNAME` → `$USER` → system login name
- If all are missing or inaccessible, the daemon prints `unknown`.

CLI integration:
- `show sessions` in the Console Server CLI prints the local CLI sessions and, when available, appends daemon sessions via `seriald-status`.

Troubleshooting “unknown” usernames:
- Ensure helpers are installed so `/usr/local/bin/seriald-client` is updated:
    ```
    sudo ./tools/seriald/install_helpers.sh
    ```
- Detach and reconnect the client (older sessions won’t retroactively gain usernames).
- Verify the installed client includes the `user` field in the attach payload:
    ```
    grep -n '"user"' /usr/local/bin/seriald-client || true
    ```
