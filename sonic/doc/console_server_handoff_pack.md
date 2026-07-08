# SONiC Console Server — Handoff Pack

**Purpose:** Authoritative project handoff for continuing the SONiC console-server integration.

**Updated:** 2026-07-08

## 1. Current milestone

Implemented and verified:

- SONiC configuration commands for console ports, groups, and users.
- SONiC display commands:
  - `show console-server port`
  - `show console-server group`
  - `show console-server user`
  - `show console-server sessions`
  - `show console-server product-info`
- SONiC interactive commands:
  - `connect console-server line <port_number>`
  - `connect console-server label <label>`
- Shared manager used by config, show, and connect command modules.
- Direct ConfigDB fast path for console-server configuration metadata.
- Runtime updates through the independent application's public commands.
- Active-session retrieval through `console-cli show sessions --json`.
- Product-info read-through cache in ConfigDB.
- Derived TCP port display in `show console-server port`.
- Password prompt mode and non-interactive password mode.
- Regression coverage for manager, config, show, and connect behavior.

Latest focused result available from the implementation work:

```text
80 passed
```

The actual repository remains the source of truth. Run the complete repository suite before merging.

## 2. Current command set

### 2.1 Port configuration

```bash
sudo config console-server port baudrate <port_number> <rate>
sudo config console-server port databits <port_number> <bits>
sudo config console-server port parity <port_number> <parity>
sudo config console-server port stopbits <port_number> <bits>
sudo config console-server port flowcontrol <port_number> <mode>
sudo config console-server port mode <port_number> <mode>
sudo config console-server port max-clients <port_number> <count>
sudo config console-server port idle-timeout <port_number> <seconds>
sudo config console-server port label <port_number> <label>
```

### 2.2 Group configuration

```bash
sudo config console-server group add <group_name> <port_list> [--role <role>]
sudo config console-server group delete <group_name>
```

Valid group roles:

```text
admin
console_user
operator
```

Default role: `console_user`.

The port list accepts friendly expressions such as:

```text
all
1-5
1-5,8,10-12
```

### 2.3 User configuration

```bash
sudo config console-server user add <username> \
    [--role <role>] \
    [--groups <group1,group2,...>] \
    [--password <value> | --prompt-password]

sudo config console-server user password <username> \
    [--password <value> | --prompt-password]

sudo config console-server user delete <username>
```

Valid user roles:

```text
none
admin
console_user
operator
```

Update semantics:

- Existing user plus omitted `--role`: preserve the existing role.
- New user plus omitted `--role`: default to `none`.
- Omitted `--groups`: preserve existing groups.
- Omitted password during metadata-only update: preserve the existing password.

### 2.4 Display commands

```bash
show console-server port
show console-server group
show console-server user
show console-server sessions
show console-server product-info
```

### 2.5 Interactive connection

```bash
connect console-server line <port_number>
connect console-server label <label>
```

The existing SONiC `connect line` and `connect device` commands are preserved.

### 2.6 Persistence

```bash
sudo config save
```

Do not add a feature-specific save command.

## 3. Architecture

### 3.1 Independent application boundary

The independent console-server application remains SONiC-agnostic.

SONiC integrates through public application commands:

```text
/usr/local/bin/seriald-status
/usr/local/bin/console-cli
```

### 3.2 Port update flow

```text
SONiC CLI validation
→ seriald-status runtime update
→ direct ConfigDB update
→ runtime rollback if ConfigDB update fails
```

No-op detection and changed-field-only updates are implemented.

### 3.3 Group update flow

```text
validate full candidate
→ one seriald-status group update
→ sequential direct ConfigDB writes
→ runtime compensation if ConfigDB update fails
```

The ConfigDB writes are not a hard Redis transaction. This is documented as a future robustness enhancement.

### 3.4 User update flow

```text
local metadata validation
→ console-cli user operation
→ direct ConfigDB metadata update
```

There is no distributed transaction across Linux/application user state and ConfigDB.

### 3.5 Session display flow

```text
show console-server sessions
→ manager.get_sessions()
→ console-cli show sessions --json
→ validate JSON
→ flatten active clients
→ SONiC table
```

Only active clients are shown. Lines with an empty client list are skipped.

Displayed fields:

```text
Line
Mode
User
Role
Client IP
Client Port
Idle Timeout
Time Left
```

`session_id` and `last_activity` are intentionally not displayed.

Session state is not stored in STATE_DB in the current implementation.

### 3.6 Product-info and TCP-port flow

ConfigDB cache entry:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
```

Fields:

```text
base_port
max_ports
max_users
max_groups
```

Read-through behavior:

```text
read ConfigDB product-info entry
→ if complete and valid, use it
→ otherwise call console-cli show product-info --json
→ validate and normalize
→ attempt best-effort ConfigDB cache write
→ return product info even if cache write fails
```

Independent application JSON:

```json
{
  "base_port": 35000,
  "no_of_user": 16,
  "no_of_group": 16,
  "no_of_port": 24
}
```

Normalized fields:

```text
base_port
max_users
max_groups
max_ports
```

`show console-server port` reads port configuration from `CONSOLE_SERVER_PORT`, obtains `base_port` through the product-info cache path, and derives:

```text
tcp_port = base_port + line
```

TCP port is not stored redundantly in each port row.

## 4. ConfigDB schema

```text
CONSOLE_SERVER_PORT|<port>
CONSOLE_SERVER_GROUP|<group>
CONSOLE_SERVER_GROUP_PORT|<group>|<port>
CONSOLE_SERVER_USER|<username>
CONSOLE_SERVER_USER_GROUP|<username>|<group>
CONSOLE_SERVER_PRODUCT_INFO|global
```

Passwords and runtime sessions are not stored in ConfigDB.

## 5. Source-tree layout

```text
sonic-utilities/
├── config/
│   ├── console_server.py
│   └── main.py
├── connect/
│   ├── console_server.py
│   └── main.py
├── show/
│   ├── console_server.py
│   └── main.py
├── sonic_console_server_manager/
│   ├── __init__.py
│   └── manager.py
└── tests/
    └── sonic_console_server_manager/
        ├── test_console_server.py
        ├── test_connect_console_server.py
        ├── test_manager.py
        └── test_show_console_server.py
```

Remove backup files such as `*_bak.py` before final submission.

## 6. Key validation rules

- Generic port range: `1..256` at schema level where applicable.
- Actual platform port limit: validate against `max_ports` or populated port inventory.
- `idle_timeout`: `0..86400`; `0` disables timeout.
- Labels must be unique.
- Reserved/default labels use `COM<port>` ownership rules.
- Group membership must reference populated console ports.
- User group names must exist.
- Passwords must never appear in show output, logs, or error messages.
- Product info must contain positive integer limits and a valid TCP range:

```text
base_port + max_ports <= 65535
```

## 7. Performance observations

Measured on a two-core ARM development system:

| Command | Real time |
|---|---:|
| `console-cli show sessions --json` | 2.455 s |
| `show console-server port` | 5.041 s |
| `show console-server sessions` | 6.095 s |

The workload is mostly CPU-bound Python/Click startup and imports. Moving from two to four cores will help system contention, but command latency depends more strongly on single-core performance, cache, memory, and storage.

A lightweight runtime-status utility may be considered later, but it is not required for correctness.

## 8. Next task

Implement boot-time ConfigDB initialization, at minimum for:

```text
CONSOLE_SERVER_PORT
```

Recommended extension:

```text
CONSOLE_SERVER_PRODUCT_INFO
```

The initialization design must define:

1. Authoritative startup source.
2. Complete default row creation for every physical console line.
3. Product-info population.
4. Idempotent behavior on repeated boots.
5. Upgrade behavior when an existing configuration is present.
6. Runtime-versus-ConfigDB synchronization direction.
7. Error handling and logging.
8. Interaction with `config save` and reboot persistence.

Do not silently overwrite user-modified ConfigDB values without an explicit ownership and upgrade policy.

## 9. Pre-merge checks

```bash
git status --short
git diff --check
git diff
pytest -v tests/sonic_console_server_manager/
python3 -m compileall \
    config/console_server.py \
    show/console_server.py \
    connect/console_server.py \
    sonic_console_server_manager/
```

On the target switch, verify every command documented in the CLI manual and execute the complete test plan.
