# Console Server ConfigDB / YANG / CVL Implementation Note

## 1. Purpose

This note records the agreed design decisions for implementing the SONiC console server configuration model.

The goal is to provide a clear direction for:

- ConfigDB table design
- `sonic-console-server.yang`
- CVL validation behavior
- CLI / REST API conversion logic
- Runtime-only data handling

This note is based on the current `cli_manual.md` and the design discussion.

---

## 2. Source CLI Scope

The CLI manual defines the following major command groups:

| Area | CLI Commands | Configuration Impact |
|---|---|---|
| Serial port physical settings | `console-cli config port` | Configures baud rate, data bits, parity, stop bits, and flow control |
| Serial port operation settings | `console-cli config operation` | Configures mode, max clients, idle timeout, and label |
| Save configuration | `console-cli config save` | Persists running config |
| User management | `console-cli config user add/delete` | User account / role / group membership |
| Group management | `console-cli config group add/delete` | Group role and port access |
| Running/startup config display | `console-cli show running-config`, `console-cli show startup-config` | Displays saved or active configuration |
| Sessions | `console-cli show sessions` | Runtime-only session state |
| Product info | `console-cli show product-info` | Read-only platform/deployment limits |
| Connect | `console-cli connect` | Runtime operation, not ConfigDB configuration |

---

## 3. Confirmed Design Decisions

| No. | Item | Decision |
|---:|---|---|
| 1 | Should `CONSOLE_SERVER_GLOBAL` be configurable or read-only platform info? | Read-only. It should not be modeled as normal writable ConfigDB data. |
| 2 | Should `groups` be a comma-separated string or a real list? | Use normalized relationship entries, similar to SONiC VLAN member modeling. |
| 3 | Should `ports` be `"all"` / `"1-5,8"` string or normalized entries? | Use normalized relationship entries. CLI/API may accept friendly syntax, but ConfigDB should store expanded entries. |
| 4 | Should port key range be fixed to `1..24` or generic `1..256`? | Use generic YANG validation and platform-specific validation in the shared config manager. Use `leafref` where possible. |
| 5 | Should `label` be unique? | Yes. Labels must be unique across console server ports. |
| 6 | Should users really be in ConfigDB? | No. User account data should not be stored in ConfigDB. Password must not be stored in ConfigDB/YANG. |
| 7 | What are runtime-only fields? | The output of `show sessions` is runtime-only data and should not be stored in ConfigDB. |

---

## 4. Proposed ConfigDB Tables

### 4.1 Writable ConfigDB Tables

The initial writable ConfigDB model should focus on serial port settings and group-to-port mapping.

```json
{
    "CONSOLE_SERVER_PORT": {
        "1": {
            "baudrate": "115200",
            "databits": "8",
            "parity": "none",
            "stopbits": "1",
            "flowcontrol": "none",
            "mode": "shared",
            "max_clients": "1",
            "idle_timeout": "600",
            "label": "COM1"
        },
        "5": {
            "baudrate": "9600",
            "databits": "8",
            "parity": "none",
            "stopbits": "1",
            "flowcontrol": "none",
            "mode": "shared",
            "max_clients": "4",
            "idle_timeout": "600",
            "label": "BackupConsole"
        }
    },

    "CONSOLE_SERVER_GROUP": {
        "Group_Default": {
            "role": "console_user"
        },
        "Group_A": {
            "role": "console_user"
        },
        "Group_C": {
            "role": "operator"
        }
    },

    "CONSOLE_SERVER_GROUP_PORT": {
        "Group_Default|1": {},
        "Group_Default|2": {},
        "Group_A|1": {},
        "Group_A|2": {},
        "Group_A|3": {},
        "Group_C|9": {},
        "Group_C|10": {},
        "Group_C|11": {},
        "Group_C|12": {}
    }
}
```

### 4.2 Not Stored in ConfigDB

Do not store the following in ConfigDB:

| Data | Reason |
|---|---|
| Product info such as `base_port`, `max_ports`, `max_users`, `max_groups` | Read-only platform/deployment data |
| User password | Security-sensitive; should be handled by local Linux account or authentication backend |
| Active sessions | Runtime state only |
| Session ID | Runtime state only |
| Writer / observer state | Runtime state only |
| Client IP / source port | Runtime state only |
| Last activity / time left | Runtime state only |

---

## 5. Normalized Relationship Tables

### 5.1 Group Membership: Item 2

The original CLI may accept:

```bash
console-cli config user add tech1 --role operator --groups Group_A,Group_B
```

However, since users should not be stored in ConfigDB, the final user/group storage depends on the authentication backend.

If group membership is ever modeled in ConfigDB or another validated database, avoid storing it as:

```json
{
    "groups": "Group_A,Group_B"
}
```

Prefer normalized relationship entries:

```json
{
    "CONSOLE_SERVER_USER_GROUP": {
        "tech1|Group_A": {},
        "tech1|Group_B": {}
    }
}
```

This follows the same concept as VLAN member mapping:

```json
{
    "VLAN_MEMBER": {
        "Vlan1000|Ethernet0": {
            "tagging_mode": "tagged"
        }
    }
}
```

The key contains the relationship. The value can be empty if the relationship has no extra attributes.

### 5.2 Group Port Mapping: Item 3

The CLI/API may accept:

```bash
console-cli config group add Group_A --ports 1-5,8,10-12
```

But ConfigDB should store expanded normalized entries:

```json
{
    "CONSOLE_SERVER_GROUP_PORT": {
        "Group_A|1": {},
        "Group_A|2": {},
        "Group_A|3": {},
        "Group_A|4": {},
        "Group_A|5": {},
        "Group_A|8": {},
        "Group_A|10": {},
        "Group_A|11": {},
        "Group_A|12": {}
    }
}
```

For `--ports all`, the shared config manager should expand it to all valid platform ports:

```text
all -> 1..max_ports
```

Example for a 24-port platform:

```json
{
    "CONSOLE_SERVER_GROUP_PORT": {
        "Group_A|1": {},
        "Group_A|2": {},
        "...": {},
        "Group_A|24": {}
    }
}
```

---

## 6. Responsibility Split

### 6.1 CLI / REST API Frontend

The CLI and REST API may accept user-friendly formats:

```bash
--ports 1-5,8,10-12
--ports all
--groups Group_A,Group_B
```

However, they should not directly own the final database conversion rules.

### 6.2 Shared Config Manager

Create a shared config manager/library used by both CLI and REST API.

Example module names:

```text
console_server_config.py
console_config_manager.py
console_db.py
```

The shared config manager should own:

| Function | Owner |
|---|---|
| Parse port range strings | Shared config manager |
| Expand `all` to `1..max_ports` | Shared config manager |
| Validate platform-specific `max_ports` | Shared config manager |
| Convert friendly CLI/API input to normalized ConfigDB entries | Shared config manager |
| Convert normalized ConfigDB entries back to show output | Shared config manager |
| Enforce label uniqueness | Shared config manager |
| Write ConfigDB entries | Shared config manager |

### 6.3 CVL / YANG

CVL should validate what can be expressed by YANG:

| Validation | CVL/YANG |
|---|---|
| Field type | Yes |
| Enum value | Yes |
| Numeric range | Yes |
| Required fields | Yes |
| Leafref existence | Yes |
| Generic port range such as `1..256` | Yes |
| Relationship table key existence | Yes, through `leafref` |
| Platform-specific `max_ports` | No, handled by shared config manager |
| Label uniqueness | Prefer shared config manager; may require additional custom validation if enforced at database level |

### 6.4 seriald Runtime Backend

The `seriald` service should consume the final normalized configuration and apply runtime behavior.

It should own:

| Runtime Behavior | Owner |
|---|---|
| Restart affected serial port service | `seriald` or backend service |
| Enforce exclusive/shared mode | `seriald` |
| Track active clients | `seriald` |
| Generate session IDs | `seriald` |
| Track writer/observer state | `seriald` |
| Track idle timeout and remaining time | `seriald` |

---

## 7. Proposed YANG Model Direction

File:

```text
src/sonic-yang-models/yang-models/sonic-console-server.yang
```

Recommended module prefix:

```yang
prefix cs;
```

Use single-line `leafref` paths in the actual `.yang` file.

Do not split paths using `+`.

### 7.1 Skeleton

```yang
module sonic-console-server {
    yang-version 1.1;

    namespace "http://github.com/sonic-net/sonic-console-server";
    prefix cs;

    description
        "SONiC console server configuration model.";

    revision 2026-06-12 {
        description
            "Initial revision.";
    }

    container sonic-console-server {
        container CONSOLE_SERVER_PORT {
            list CONSOLE_SERVER_PORT_LIST {
                key "port";

                leaf port {
                    type uint16 {
                        range "1..256";
                    }
                    description
                        "Serial line number.";
                }

                leaf baudrate {
                    type enumeration {
                        enum 300;
                        enum 1200;
                        enum 2400;
                        enum 4800;
                        enum 9600;
                        enum 19200;
                        enum 38400;
                        enum 57600;
                        enum 115200;
                        enum 230400;
                        enum 460800;
                        enum 921600;
                    }
                    default "115200";
                }

                leaf databits {
                    type uint8 {
                        range "5..8";
                    }
                    default "8";
                }

                leaf parity {
                    type enumeration {
                        enum none;
                        enum even;
                        enum odd;
                        enum mark;
                        enum space;
                    }
                    default "none";
                }

                leaf stopbits {
                    type uint8 {
                        range "1..2";
                    }
                    default "1";
                }

                leaf flowcontrol {
                    type enumeration {
                        enum none;
                        enum rtscts;
                        enum xonxoff;
                    }
                    default "none";
                }

                leaf mode {
                    type enumeration {
                        enum exclusive;
                        enum shared;
                    }
                    default "shared";
                }

                leaf max_clients {
                    type uint8 {
                        range "1..4";
                    }
                    default "1";
                }

                leaf idle_timeout {
                    type uint32;
                    default "600";
                    description
                        "Idle timeout in seconds. Value 0 disables timeout.";
                }

                leaf label {
                    type string {
                        length "1..16";
                    }
                    description
                        "Unique user-friendly serial line label.";
                }
            }
        }

        container CONSOLE_SERVER_GROUP {
            list CONSOLE_SERVER_GROUP_LIST {
                key "groupname";

                leaf groupname {
                    type string {
                        length "1..32";
                    }
                }

                leaf role {
                    type enumeration {
                        enum operator;
                        enum console_user;
                        enum admin;
                    }
                    default "console_user";
                }
            }
        }

        container CONSOLE_SERVER_GROUP_PORT {
            list CONSOLE_SERVER_GROUP_PORT_LIST {
                key "groupname port";

                leaf groupname {
                    type leafref {
                        path "/cs:sonic-console-server/cs:CONSOLE_SERVER_GROUP/cs:CONSOLE_SERVER_GROUP_LIST/cs:groupname";
                    }
                }

                leaf port {
                    type leafref {
                        path "/cs:sonic-console-server/cs:CONSOLE_SERVER_PORT/cs:CONSOLE_SERVER_PORT_LIST/cs:port";
                    }
                }
            }
        }
    }
}
```

---

## 8. Label Uniqueness

Decision: console port labels must be unique.

Example invalid configuration:

```json
{
    "CONSOLE_SERVER_PORT": {
        "1": {
            "label": "BackupConsole"
        },
        "2": {
            "label": "BackupConsole"
        }
    }
}
```

Recommended first implementation:

```text
Enforce label uniqueness in the shared config manager.
```

Reason:

```text
YANG/CVL does not easily enforce uniqueness of a non-key leaf across all list entries in a simple and maintainable way.
```

The shared config manager should reject duplicate labels before writing ConfigDB.

Example error:

```text
Duplicate console port label 'BackupConsole'. Labels must be unique.
```

---

## 9. Platform max_ports Handling

Do not hard-code `1..24` in YANG.

Recommended design:

```text
YANG: generic range 1..256
Shared config manager: platform-specific max_ports check
CVL: leafref validates that group-port mappings refer to defined CONSOLE_SERVER_PORT entries
```

Example:

```text
Platform max_ports = 24
CLI/API input: --ports 1-25
Result: reject port 25 before writing ConfigDB
```

Expected error:

```text
Invalid port 25. Valid range is 1..24.
```

---

## 10. Runtime-only Fields

The following fields from `show sessions` are runtime-only and should not be modeled as writable ConfigDB:

```text
session_id
user
role in active session
client IP
client source port
writer
clients count
writers count
observers count
idle_timeout remaining time
last_activity
time_left
```

These should be generated and reported by `seriald`.

If state YANG is required later, create a separate operational/state model. Do not mix runtime session state into ConfigDB YANG.

---

## 11. Implementation Checklist

### 11.1 YANG / CVL

- [ ] Create `yang-models/sonic-console-server.yang`
- [ ] Use `prefix cs`
- [ ] Use single-line `leafref` paths
- [ ] Add `CONSOLE_SERVER_PORT`
- [ ] Add `CONSOLE_SERVER_GROUP`
- [ ] Add `CONSOLE_SERVER_GROUP_PORT`
- [ ] Do not add writable `CONSOLE_SERVER_GLOBAL`
- [ ] Do not add users/passwords to ConfigDB YANG
- [ ] Add file to `setup.py` `yang_files`
- [ ] Run `pyang`
- [ ] Build `sonic-yang-models`
- [ ] Confirm generated/copied model appears under `cvlyang-models`

### 11.2 Shared Config Manager

- [ ] Implement port range parser
- [ ] Implement `all` expansion using platform `max_ports`
- [ ] Implement platform port validation
- [ ] Implement ConfigDB writer for normalized `CONSOLE_SERVER_GROUP_PORT`
- [ ] Implement reverse conversion for show commands
- [ ] Implement label uniqueness check
- [ ] Share the same manager between CLI and REST API

### 11.3 CLI

- [ ] `console-cli config port`
- [ ] `console-cli config operation`
- [ ] `console-cli config group add`
- [ ] `console-cli config group delete`
- [ ] `console-cli show running-config`
- [ ] `console-cli show startup-config`
- [ ] `console-cli show sessions`
- [ ] `console-cli show product-info`
- [ ] `console-cli connect`

### 11.4 Runtime Backend

- [ ] `seriald` reads normalized configuration
- [ ] Apply port setting changes
- [ ] Apply mode/max-client/idle-timeout behavior
- [ ] Enforce group-to-port access
- [ ] Generate runtime session output

---

## 12. Recommended First Implementation Scope

Start with:

```text
CONSOLE_SERVER_PORT
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
```

Defer:

```text
User storage in ConfigDB
Password storage in ConfigDB
Writable global/product-info table
Runtime session state in ConfigDB
```

This keeps the first YANG/CVL implementation focused and avoids security-sensitive or runtime-only data.

---

## 13. SONiC CLI Command Convention

The console server feature should expose native SONiC-style commands.

### 13.1 Feature Name

Use:

```text
console-server
```

Do not use:

```text
consoleserver
console_server
```

Reason:

- `console-server` is clearer for a multiword feature name.
- It matches the YANG model name `sonic-console-server.yang`.
- It avoids using the overly broad name `console`.
- It fits common SONiC CLI naming style for multiword feature groups.

### 13.2 Command Hierarchy

Do not place `show` or `connect` operations below the top-level `config` command.

Incorrect:

```bash
config consoleserver config
config consoleserver show
config consoleserver connect
```

Recommended structure:

```bash
# Configuration
sudo config console-server port <port_number> [OPTIONS]
sudo config console-server operation <port_number> [OPTIONS]
sudo config console-server group add <group_name> [OPTIONS]
sudo config console-server group del <group_name>

# Display
show console-server running-config
show console-server startup-config
show console-server sessions
show console-server product-info

# Interactive connection
connect line <port_number>

# Persist ConfigDB
sudo config save
```

### 13.3 Configuration Examples

```bash
sudo config console-server port 5 \
    --baudrate 9600 \
    --databits 8 \
    --parity none \
    --stopbits 1 \
    --flowcontrol none
```

```bash
sudo config console-server operation 5 \
    --mode shared \
    --max-clients 4 \
    --idle-timeout 600 \
    --label BackupConsole
```

```bash
sudo config console-server group add Group_A \
    --role console_user \
    --ports 1-5,8,10-12
```

The CLI may accept a friendly port range, but the shared config manager must convert it into normalized `CONSOLE_SERVER_GROUP_PORT` entries before writing ConfigDB.

### 13.4 Show Command Examples

```bash
show console-server running-config
show console-server running-config --port 5
show console-server running-config --groups

show console-server startup-config
show console-server sessions
show console-server sessions --port 5
show console-server sessions --json

show console-server product-info
```

`show console-server sessions` displays runtime-only data supplied by `seriald`.

### 13.5 Connect Command

Use:

```bash
connect line <port_number>
```

Example:

```bash
connect line 3
```

Do not use:

```bash
config console-server connect 3
```

Connection is a runtime action, not a configuration operation.

Fallback, only if integration requires it:

```bash
connect console-server <port_number>
```

### 13.6 Save Command

Do not add:

```bash
config console-server save
```

Use the standard SONiC command:

```bash
sudo config save
```

### 13.7 Shared Implementation

The SONiC CLI and REST API should call the same shared config manager:

```text
SONiC CLI ─┐
           ├─> shared console-server config manager
REST API ──┘          │
                      ├─ normalize groups and ports
                      ├─ validate platform max_ports
                      ├─ enforce unique labels
                      ├─ invoke CVL/schema validation
                      └─ write ConfigDB
```

This prevents the CLI and REST API from applying different conversion or validation rules.

