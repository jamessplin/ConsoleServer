# Console Server ConfigDB / YANG / CVL Design Note

## 1. Purpose

This note records the agreed design decisions for implementing the SONiC console server configuration model.

The goal is to provide a clear direction for:

- ConfigDB table design
- `sonic-console-server.yang`
- CVL validation behavior
- CLI / REST API conversion logic
- Runtime-only data handling

This note is based on the current `cli_manual.md` and the design discussion.



## 1.1 Related Implementation Documents

Detailed Linux/NSS/PAM user-management behavior is defined in:

```text
console_server_user_management_implementation.md
```

This design note defines the data model, interfaces, validation ownership, and component boundaries. The linked implementation guide defines Linux account operations, transactions, rollback behavior, security requirements, and tests.

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
| 6 | Should users really be in ConfigDB? | Store only non-secret console-server user metadata (`username`, `role`, and normalized group membership) in ConfigDB. Linux account data and passwords are not stored in ConfigDB. Password is accepted only as a CLI/REST operation input and is written directly to the Linux authentication backend. |
| 7 | What are runtime-only fields? | The output of `show sessions` is runtime-only data and should not be stored in ConfigDB. |

---

## 4. Proposed ConfigDB Tables

### 4.1 Writable ConfigDB Tables

The writable ConfigDB model includes serial port settings, groups, group-to-port mappings, and non-secret console-server user metadata. Passwords and Linux authentication data remain outside ConfigDB.

`CONSOLE_SERVER_PORT` is a platform-initialized complete table. During initialization, one entry must be created for every valid physical console port from `1` through `max_ports`. Each entry contains the effective default serial and operational settings, including the default label `COM<port>`.

For brevity, the example below shows only selected `CONSOLE_SERVER_PORT` entries. The actual table contains every valid platform port so all `CONSOLE_SERVER_GROUP_PORT.port` leafrefs can resolve.


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
        "Group_B": {
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
    },

    "CONSOLE_SERVER_USER": {
        "tech1": {
            "role": "operator"
        },
        "guest": {
            "role": "none"
        }
    },

    "CONSOLE_SERVER_USER_GROUP": {
        "tech1|Group_A": {},
        "tech1|Group_B": {},
        "guest|Group_Default": {}
    }
}
```

### 4.2 Not Stored in ConfigDB

Do not store the following in ConfigDB:

| Data | Reason |
|---|---|
| Product info such as `base_port`, `max_ports`, `max_users`, `max_groups` | Read-only platform/deployment data |
| Linux account data and user password | Security-sensitive; handled by the Linux authentication backend. Password is accepted only as an operation input and is never stored in ConfigDB. |
| Active sessions | Runtime state only |
| Session ID | Runtime state only |
| Writer / observer state | Runtime state only |
| Client IP / source port | Runtime state only |
| Last activity / time left | Runtime state only |

---

## 5. Normalized Relationship Tables

### 5.1 Group Membership: Item 2

The CLI may accept:

```bash
console-cli config user add tech1 --role operator --groups Group_A,Group_B --password <password>
```

Store only non-secret user metadata in ConfigDB:

```json
{
    "CONSOLE_SERVER_USER": {
        "tech1": {
            "role": "operator"
        }
    },

    "CONSOLE_SERVER_USER_GROUP": {
        "tech1|Group_A": {},
        "tech1|Group_B": {}
    }
}
```

The password is not written to ConfigDB. It is accepted only by the CLI/REST user-management operation and is written directly to the Linux authentication backend.

This follows the same normalized relationship concept as VLAN member mapping:

```json
{
    "VLAN_MEMBER": {
        "Vlan1000|Ethernet0": {
            "tagging_mode": "tagged"
        }
    }
}
```

The composite key contains the relationship. The value can be empty if the relationship has no extra attributes.

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
| Initialize `CONSOLE_SERVER_PORT` entries for `1..max_ports` | Platform initialization / shared config manager |
| Populate default settings and `COM<port>` labels | Platform initialization / shared config manager |
| Parse port range strings | Shared config manager |
| Expand `all` to `1..max_ports` | Shared config manager |
| Validate platform-specific `max_ports` | Shared config manager |
| Convert friendly CLI/API input to normalized ConfigDB entries | Shared config manager |
| Convert normalized ConfigDB entries back to show output | Shared config manager |
| Normalize missing or blank labels to `COM<port>` | Shared config manager |
| Enforce reserved `COM<port>` ownership and label uniqueness after normalization | Shared config manager |
| Write ConfigDB entries | Shared config manager |
| Validate local Linux user existence | Shared config manager / user-management backend |
| Create/delete Linux user and set password | Linux user-management backend |
| Persist non-secret user role/group metadata | Shared config manager |

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
| Linux user existence | No; validate through the shared manager/user-management backend |
| Platform-specific `max_ports` | No, handled by shared config manager |
| Label uniqueness | Yes, through `unique "label"`; shared manager also checks early for clearer errors |

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

### 7.1 Authoritative YANG File

The authoritative schema, including ConfigDB data nodes and user-management RPC inputs, is maintained in:

```text
src/sonic-yang-models/yang-models/sonic-console-server.yang
```

For this review, the validated file is provided as:

```text
sonic-console-server.yang
```

This design note records the rationale and acceptance criteria only. The embedded draft skeleton has been removed to avoid drift between the design note and the implementation.

The accepted file version is identified by the `pyang` version, validation command and result, generated tree output, and SHA-256 hash recorded in Section 7.3.

---

### 7.2 Design Rationale

The authoritative YANG file contains several non-obvious modeling choices. The table below records the reasoning for each one so implementers do not revisit settled decisions.

| Choice | Rationale |
|---|---|
| `baudrate` as `uint32` with a discrete allowed-value range, not `enumeration` | YANG `enumeration` assigns string identity names to each value. A `uint32` range with discrete values (`300 \| 1200 \| ...`) keeps the leaf numeric and machine-comparable, which aligns with how SONiC models similar integer-valued constraints. |
| `unique "label"` on the list, not a `must` expression | `unique` is the YANG 1.1 idiomatic statement for enforcing non-key leaf uniqueness across list entries. A `must` XPath over the full list is harder to maintain and less portable across CVL implementations. |
| Dynamic default port label | YANG cannot express a default derived from another leaf, such as `COM<port>`. The shared config manager must normalize an omitted label for a new port, or an explicitly blank label, to `COM<port>` before CVL validation and ConfigDB write. The YANG leaf is optional for schema consistency, but platform initialization and all supported writers must materialize a non-empty effective label in ConfigDB. |
| Reserved `COM<port>` labels | `COM1` through `COM<max_ports>` are reserved for their matching ports so every port can always be reset to its deterministic default. Reserved-name matching is case-insensitive, and reserved labels are stored canonically in uppercase. |
| `leafref` for both keys of `CONSOLE_SERVER_GROUP_PORT_LIST` | Enforces referential integrity at the CVL level. A group-port mapping entry for a non-existent group or port is rejected at write time, preventing orphan entries. |
| Complete `CONSOLE_SERVER_PORT` population | The platform initializes one entry for every valid physical console port from `1` through `max_ports`. This allows `CONSOLE_SERVER_GROUP_PORT.port` to use a `leafref`, prevents mappings to nonexistent ports, and ensures every physical port always has effective defaults and a `COM<port>` label. |
| `idle_timeout` range `0..86400` with `0` meaning disabled | Avoids a separate boolean flag. `0` is the conventional sentinel for "no timeout" across SONiC models. `86400` seconds (24 hours) is the approved upper bound. |
| No `CONSOLE_SERVER_GLOBAL` container | Product and platform info such as `base_port`, `max_ports`, `max_users`, and `max_groups` is read-only deployment metadata. It must not be modeled as writable ConfigDB data. |
| User metadata without password leaf | `CONSOLE_SERVER_USER` stores only non-secret metadata such as username and role. `CONSOLE_SERVER_USER_GROUP` stores normalized membership. Password is never a ConfigDB leaf; it is accepted only as a CLI/REST operation input and is written to the Linux authentication backend. |

---


The `CONSOLE_SERVER_USER_GROUP.username` leafref validates only ConfigDB referential integrity. It does not prove that the corresponding Linux/NSS account exists. For an existing user, the shared manager must validate that the account exists in the configured Linux/NSS authentication backend before updating ConfigDB metadata. For a new user, the Linux account must be created successfully before `CONSOLE_SERVER_USER` and `CONSOLE_SERVER_USER_GROUP` are committed.

Implementation details are defined in `console_server_user_management_implementation.md`.


### 7.2.1 Password Operation Input

Standard YANG does not provide a general write-only configuration leaf. Therefore, `password` must not be added to `CONSOLE_SERVER_USER`.

Password must be modeled only as a transient CLI/REST operation input.

Required behavior:

```text
New Linux user:
    password is required

Existing Linux user:
    password is optional; when omitted, the current password is unchanged

Existing Linux user without CONSOLE_SERVER_USER metadata:
    create/import the missing ConfigDB metadata without recreating the Linux account
```

The password must never be stored in ConfigDB, returned by REST GET/show commands, printed in logs, or included in error messages.

Detailed RPC/action examples, backend behavior, transaction ordering, rollback, and security requirements are defined in:

```text
console_server_user_management_implementation.md
```

### 7.3 `pyang` Acceptance Gate

The exact YANG file has passed the initial `pyang` acceptance gate recorded below.

Before coding starts, perform and record the following:

```bash
pyang --version
pyang sonic-console-server.yang
echo $?
pyang -f tree sonic-console-server.yang > sonic-console-server.tree
sha256sum sonic-console-server.yang
```

Acceptance criteria:

```text
Validation result: PASS
Exit code: 0
Tree output: generated successfully
```

Lock the accepted version in this document:

```text
Validated file:
sonic-console-server.yang

pyang version:
__main__.py 2.7.1

Validation command:
python -m pyang sonic-console-server.yang

Validation result:
PASS

File SHA-256:
70cad005e348df60e7985a9ce751a8a755bf12922ee4bf08e6ece2223c7481b9
```

Section 7 is implementation-ready for schema syntax review. Repository integration and SONiC CVL build validation remain separate follow-up steps.


## 8. Label Defaulting and Uniqueness

Decision: every stored console port entry must contain a non-empty, unique label.

Default and reset rules:

```text
New port, label omitted:
    store COM<port>

New port, label blank:
    store COM<port>

Existing port, label option omitted:
    preserve the current label

Existing port, label explicitly blank:
    reset the label to COM<port>
```

YANG cannot express the dynamic default `COM<port>`, so the shared config manager must perform this normalization before CVL validation and ConfigDB write.
Although the YANG `label` leaf is optional, every valid runtime `CONSOLE_SERVER_PORT` entry must contain an explicitly materialized label in ConfigDB. Platform initialization and all supported CLI/REST writers must preserve this invariant. Backend applications may rely on the label being present and must not implement their own fallback logic.


Example:

```text
port 5 + missing/blank label -> COM5
```

The YANG list should continue to enforce uniqueness for physically stored labels. The `label` leaf is not marked `mandatory`; instead, platform initialization and all supported CLI/REST writers must materialize a non-empty effective label in ConfigDB:

```yang
list CONSOLE_SERVER_PORT_LIST {
    key "port";
    unique "label";
```

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

Validation should be performed at two levels:

| Layer | Responsibility |
|---|---|
| Shared config manager | Materialize `COM<port>`, enforce reserved-name ownership, and validate effective-label uniqueness before ConfigDB write |
| YANG/CVL | Enforce string constraints and uniqueness for physically stored label values through `unique "label"` |


### 8.1 Label Normalization

The shared config manager should expose:

```python
def normalize_port_label(port: int, label: str | None) -> str:
    """Return COM<port> when label is missing or blank."""
```

Required behavior:

```python
def normalize_port_label(port: int, label: str | None) -> str:
    if label is None:
        return f"COM{port}"

    normalized = label.strip()
    if not normalized:
        return f"COM{port}"

    return normalized
```

Reserved default labels must be validated before the general uniqueness check.

Labels in the form `COM<port>` are reserved default labels. A reserved label may only be assigned to its corresponding console port. Matching is case-insensitive.

Examples:

```text
port 5, blank label  -> normalize to COM5 and accept
port 5, COM5         -> accept
port 5, com5         -> normalize/canonicalize to COM5 and accept
port 2, COM5         -> reject; COM5 is reserved for port 5
port 2, com5         -> reject; COM5 is reserved for port 5
```

Recommended error:

```text
Error: Label 'COM5' is reserved for console port 5.
```

The shared manager must not automatically rename an existing label or generate an alternative such as `COM5-1`. The request must be rejected so the user can choose a valid custom label.

After reserved-name validation, the normalized label must also pass the general uniqueness check.


The shared config manager should also expose:

```python
def validate_reserved_port_label(port: int, label: str, max_ports: int) -> None:
    """Reject COM<M> when M is a valid port number different from port."""
```

Recommended behavior:

```python
import re

_RESERVED_LABEL_RE = re.compile(r"^COM([0-9]+)$", re.IGNORECASE)


def validate_reserved_port_label(
    port: int,
    label: str,
    max_ports: int,
) -> None:
    match = _RESERVED_LABEL_RE.fullmatch(label.strip())
    if not match:
        return

    reserved_port = int(match.group(1))
    if 1 <= reserved_port <= max_ports and reserved_port != port:
        raise ReservedPortLabelError(
            f"Label 'COM{reserved_port}' is reserved for console port "
            f"{reserved_port}."
        )
```

Canonical storage should use uppercase `COM<port>` for reserved default labels.
General custom-label uniqueness is case-sensitive. Only reserved `COM<port>` matching is case-insensitive. Leading and trailing whitespace is removed before validation and storage.


### 8.2 Error Contract

Use the following fixed error contract:

| Condition | CLI result | REST result |
|---|---|---|
| Duplicate custom or normalized label | Exit code `1`; error code `CONSOLE_SERVER_LABEL_DUPLICATE` | `409 Conflict`; error code `CONSOLE_SERVER_LABEL_DUPLICATE` |
| Reserved default label assigned to the wrong port | Exit code `1`; error code `CONSOLE_SERVER_LABEL_RESERVED` | `409 Conflict`; error code `CONSOLE_SERVER_LABEL_RESERVED` |

Common fields:

| Field | Value |
|---|---|
| Error field | `label` |
| Duplicate-label message | `Console port label '<label>' is already used by port <port>.` |
| Reserved-label message | `Label '<label>' is reserved for console port <port>.` |

CLI example:

```text
Error: Console port label 'BackupConsole' is already used by port 1.
```

REST example:

```json
{
    "error": {
        "code": "CONSOLE_SERVER_LABEL_DUPLICATE",
        "message": "Console port label 'BackupConsole' is already used by port 1.",
        "field": "label"
    }
}
```


Reserved-label CLI example:

```text
Error: Label 'COM5' is reserved for console port 5.
```

Reserved-label REST example:

```json
{
    "error": {
        "code": "CONSOLE_SERVER_LABEL_RESERVED",
        "message": "Label 'COM5' is reserved for console port 5.",
        "field": "label"
    }
}
```

## 9. Platform max_ports Handling

Do not hard-code `1..24` in YANG.

Recommended design:

```text
Platform initialization:
    create CONSOLE_SERVER_PORT entries for every port in 1..max_ports
    populate each entry with default settings and label COM<port>

YANG:
    use a generic key range of 1..256

Shared config manager:
    reject user input outside 1..max_ports

CVL:
    validate that every CONSOLE_SERVER_GROUP_PORT mapping references an
    existing CONSOLE_SERVER_PORT entry
```

Physical `CONSOLE_SERVER_PORT` entries are platform-owned. Normal CLI and REST operations may update their attributes but must not create or delete individual physical port entries.

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
- [ ] Model `baudrate` as restricted `uint32`
- [ ] Set `idle_timeout` range to `0..86400`
- [ ] Add `CONSOLE_SERVER_PORT`
- [ ] Initialize `CONSOLE_SERVER_PORT` for every valid port in `1..max_ports`
- [ ] Populate each port with default settings and `COM<port>` label
- [ ] Prevent normal CLI/REST operations from creating or deleting physical port entries
- [ ] Add `CONSOLE_SERVER_GROUP`
- [ ] Add `CONSOLE_SERVER_GROUP_PORT`
- [ ] Add `CONSOLE_SERVER_USER` for non-secret username/role metadata
- [ ] Add `CONSOLE_SERVER_USER_GROUP` for normalized membership
- [ ] Do not add writable `CONSOLE_SERVER_GLOBAL`
- [ ] Do not add `password` as a ConfigDB leaf
- [ ] Add `unique "label"` to `CONSOLE_SERVER_PORT_LIST`
- [ ] Keep `label` optional in YANG for consistency with other leaves
- [ ] Materialize a non-empty effective label in every ConfigDB port entry
- [ ] Validate stored label type and length
- [ ] Validate the final YANG with `pyang`
- [ ] Record the accepted `pyang` version and file SHA-256
- [ ] Add the file to `setup.py` `yang_files`
- [ ] Build `sonic-yang-models`
- [ ] Confirm the generated/copied model appears under `cvlyang-models`

### 11.2 Shared Config Manager

- [ ] Implement `parse_port_expression(expression)`
- [ ] Implement `validate_ports(ports, max_ports)`
- [ ] Implement `normalize_group_ports(group_name, ports)`
- [ ] Implement `normalize_port_label(port, label)`
- [ ] Normalize a missing new-port label to `COM<port>`
- [ ] Treat an explicitly blank existing-port label as reset to `COM<port>`
- [ ] Reserve `COM1..COM<max_ports>` for their matching ports
- [ ] Match reserved labels case-insensitively
- [ ] Store reserved default labels canonically as uppercase `COM<port>`
- [ ] Implement reserved-label ownership validation
- [ ] Implement label uniqueness checking after normalization
- [ ] Implement `set_port_config(port, updates)`
- [ ] Implement `set_group_ports(group_name, expression)`
- [ ] Implement `write_transaction(operations)`
- [ ] Implement reverse conversion for show commands
- [ ] Validate platform-specific `max_ports`
- [ ] Verify every `CONSOLE_SERVER_GROUP_PORT` mapping resolves to an existing port entry
- [ ] Validate Linux/NSS user existence for existing users
- [ ] Require password only when creating a new Linux user
- [ ] Keep the existing password unchanged when omitted for an existing user
- [ ] Import an existing Linux user when ConfigDB metadata is missing
- [ ] Create a new Linux account before committing new ConfigDB metadata
- [ ] Persist only non-secret user metadata to ConfigDB
- [ ] Never store or return passwords
- [ ] Implement rollback for Linux-account/ConfigDB partial failure
- [ ] Share the same manager between CLI and REST API

### 11.3 SONiC CLI and console-cli Integration

#### SONiC Configuration Commands

- [ ] `config console-server port baudrate`
- [ ] `config console-server port databits`
- [ ] `config console-server port parity`
- [ ] `config console-server port stopbits`
- [ ] `config console-server port flowcontrol`
- [ ] `config console-server port mode`
- [ ] `config console-server port max-clients`
- [ ] `config console-server port idle-timeout`
- [ ] `config console-server port label`
- [ ] `config console-server group add`
- [ ] `config console-server group del`
- [ ] `config console-server user add`
- [ ] `config console-server user del`

#### SONiC Display and Runtime Commands

- [ ] `show console-server port`
- [ ] `show console-server group`
- [ ] `show console-server user`
- [ ] `show console-server sessions`
- [ ] `show console-server product-info`
- [ ] `connect line <port_number>`
- [ ] Use standard `config save` for persistence

#### Existing console-cli Paths

- [ ] `console-cli config port`
- [ ] `console-cli config operation`
- [ ] `console-cli config group add`
- [ ] `console-cli config group delete`
- [ ] `console-cli config user add`
- [ ] `console-cli config user delete`
- [ ] `console-cli show running-config`
- [ ] `console-cli show startup-config`
- [ ] `console-cli show sessions --json`
- [ ] `console-cli show product-info`
- [ ] `console-cli connect`

### 11.4 Runtime Backend

- [ ] `seriald` reads normalized configuration
- [ ] Apply port setting changes
- [ ] Apply mode/max-client/idle-timeout behavior
- [ ] Enforce group-to-port access
- [ ] Track active clients and writer/observer state
- [ ] Generate session IDs
- [ ] Expose session data through the existing `seriald` socket/internal API
- [ ] Provide machine-readable JSON through `console-cli show sessions --json`
- [ ] Keep interactive console traffic on the existing `console-cli connect` / `seriald` path
- [ ] Do not use `STATE_DB` for session display or interactive data in the first implementation


## 12. Initial Implementation Scope

Start with:

```text
CONSOLE_SERVER_PORT
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
CONSOLE_SERVER_USER
CONSOLE_SERVER_USER_GROUP
```

Do not implement:

```text
Password storage in ConfigDB
Writable global/product-info table
Runtime session state in ConfigDB
```

User role and group membership are in scope as non-secret ConfigDB metadata. Linux account creation and password handling remain in the Linux authentication backend.

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
sudo config console-server port baudrate <port_number> <rate>
sudo config console-server port databits <port_number> <bits>
sudo config console-server port parity <port_number> <parity>
sudo config console-server port stopbits <port_number> <bits>
sudo config console-server port flowcontrol <port_number> <mode>

# Operational configuration
sudo config console-server port mode <port_number> <mode>
sudo config console-server port max-clients <port_number> <count>
sudo config console-server port idle-timeout <port_number> <seconds>
sudo config console-server port label <port_number> <label>

# Group configuration
sudo config console-server group add <group_name> \
    --role <role> \
    --ports <port_list>
sudo config console-server group del <group_name>

# User configuration
# The same command supports both create and update.
# For a new Linux user, `--password` is required.
# For an existing Linux user, `--password` is optional; when omitted, the existing password is unchanged.
sudo config console-server user add <username> \
    [--password <password>] \
    [--role <role>] \
    [--groups <group1,group2,...>]

sudo config console-server user del <username>

# Display
show console-server port
show console-server group
show console-server user
show console-server sessions
show console-server product-info

# Interactive connection
connect line <port_number>

# Persist ConfigDB
sudo config save
```

### 13.3 Configuration Examples

```bash
sudo config console-server port baudrate 5 115200
sudo config console-server port databits 5 8
sudo config console-server port parity 5 none
sudo config console-server port stopbits 5 1
sudo config console-server port flowcontrol 5 rtscts

sudo config console-server port mode 5 shared
sudo config console-server port max-clients 5 4
sudo config console-server port idle-timeout 5 600
sudo config console-server port label 5 BackupConsole

sudo config console-server group add Group_A \
    --role console_user \
    --ports 1-5,8,10-12
sudo config console-server group del Group_A

sudo config console-server user add tech1 \
    --password 'ChangeMe_123!' \
    --role operator \
    --groups Group_A,Group_B
sudo config console-server user del tech1
```

The CLI may accept a friendly port range, but the shared config manager must convert it into normalized `CONSOLE_SERVER_GROUP_PORT` entries before writing ConfigDB.

### 13.4 Show Command Examples

Recommended structure:

```bash
show console-server port
show console-server group
show console-server user
show console-server sessions
show console-server product-info
```

Use them like this:

- `show console-server port` — Shows the current effective port configuration, such as baud rate, data bits, parity, stop bits, flow control, mode, maximum clients, idle timeout, and label.

- `show console-server group` — Shows configured groups, roles, and permitted ports.

- `show console-server user` — Shows users, assigned roles, and group membership. Do not display passwords.

- `show console-server sessions` — Shows runtime session status only, such as connected users, source addresses, port number, connection time, idle time, and session mode.

- `show console-server product-info` — Shows hardware or product information.


`tcp_port` is a derived runtime/display value and is not stored as an independent ConfigDB field.

```text
tcp_port = base_port + serial_port
```

Example:

```text
base_port = 35000
serial_port = 1
tcp_port = 35001
```

The `base_port` value comes from read-only product/platform information.

For example:

```text
admin@sonic:~$ show console-server port

Port  Label          Baudrate  Data  Parity  Stop  Flow  Mode    Max Clients  Idle Timeout   tcp_port
----  -------------  --------  ----  ------  ----  ----  ------  -----------  ------------   --------
1     Router-01      9600      8     none    1     none  shared  4            600             35001
2     Switch-02      115200    8     none    1     none  exclusive  1         0               35002
```

```text
admin@sonic:~$ show console-server group
group          port_list                                                                              role
-------------  -------------------------------------------------------------------------------------  ------------
Group_Default  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24  console_user
Group_A         1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15                                              admin
Group_B         13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24                                             admin
```

```text
admin@sonic:~$ show console-server user
user   group          role
-----  -------------  --------
admin  Group_Default  admin
bmc    Group_Default  admin
bob    Group_A         none
ted    Group_B         operator
```

```text
admin@sonic:~$ show console-server product-info
Product Configuration & Limits
------------------------------
Base Port        : 35000
Max Groups       : 16
Max Ports        : 24
Max Users        : 16
```

And separately:

```text
admin@sonic:~$ show console-server sessions

- line 1 [exclusive] : writer=ted (clients=3, writers=1, observers=2)
    - ted role=writer session_id=5f2a3b7c ip=127.0.0.1 port=40262 [timeout=600s, left=455s]
    - ted role=observer session_id=8c9d1204 ip=127.0.0.1 port=60854 [timeout=600s, left=502s]
    - alice role=observer session_id=2f01aa91 ip=127.0.0.1 port=48464 [timeout=600s, left=577s]
- line 2 [shared] : writer=n/a (clients=0, writers=0, observers=0)
```

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

### 13.7 Command Mapping: SONiC vs console-cli

#### Serial Port Configuration

| SONiC Command | console-cli Equivalent |
|---|---|
| `sudo config console-server port baudrate <port> <rate>` | `console-cli config port {port} --baudrate <rate>` |
| `sudo config console-server port databits <port> <bits>` | `console-cli config port {port} --databits <bits>` |
| `sudo config console-server port parity <port> <parity>` | `console-cli config port {port} --parity <type>` |
| `sudo config console-server port stopbits <port> <bits>` | `console-cli config port {port} --stopbits <bits>` |
| `sudo config console-server port flowcontrol <port> <mode>` | `console-cli config port {port} --flowcontrol <method>` |

#### Operational Configuration

| SONiC Command | console-cli Equivalent |
|---|---|
| `sudo config console-server port mode <port> <mode>` | `console-cli config operation {port} --mode <mode>` |
| `sudo config console-server port max-clients <port> <count>` | `console-cli config operation {port} --max-clients <count>` |
| `sudo config console-server port idle-timeout <port> <seconds>` | `console-cli config operation {port} --idle-timeout <seconds>` |
| `sudo config console-server port label <port> <label>` | `console-cli config operation {port} --label <label>` |

#### Group Management

| SONiC Command | console-cli Equivalent |
|---|---|
| `sudo config console-server group add <name> --role <role> --ports <list>` | `console-cli config group add {name} --role <role> --ports <list>` |
| `sudo config console-server group del <name>` | `console-cli config group delete {name}` |

#### User Management

| SONiC Command | console-cli Equivalent |
|---|---|
| `sudo config console-server user add <user> [--password <pwd>] [--role <role>] [--groups <groups>]` | `console-cli config user add {user} [--password <pwd>] [--role <role>] [--groups <groups>]` |
| `sudo config console-server user del <user>` | `console-cli config user delete {user}` |


Password handling for both SONiC CLI and `console-cli`:

```text
New Linux user:
    --password is required.

Existing Linux user:
    --password is optional.
    If omitted, the existing password remains unchanged.

Existing Linux user without CONSOLE_SERVER_USER metadata:
    treat the command as an import/update operation;
    create the missing ConfigDB metadata without recreating the Linux account.
```

#### Display Commands

| SONiC Command | console-cli Equivalent |
|---|---|
| `show console-server port` | `console-cli show running-config --line all` |
| `show console-server group` | `console-cli show running-config --groups` |
| `show console-server user` | `console-cli show running-config --users` |
| `show console-server sessions` | `console-cli show sessions --json` |
| `show console-server product-info` | `console-cli show product-info` |

#### Connection

| SONiC Command | console-cli Equivalent |
|---|---|
| `connect line <port>` | `console-cli connect {port}` |

**Key Differences:**
- SONiC uses **action-then-value** syntax: `port baudrate <port> <rate>` (splits port config into individual property subcommands)
- console-cli uses **unified option syntax**: `config port {port} --baudrate <rate>` (all serial settings on one command)
- SONiC exposes each property as an individual subcommand under `console-server port`; `console-cli` separates physical settings and operational settings into `config port` and `config operation`.
- SONiC requires `sudo` prefix; console-cli invokes directly
- Verb forms: SONiC uses short forms (`del`); console-cli uses `delete`

### 13.8 Shared Implementation

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

### 13.8.1 Minimum Shared-Manager API

The shared config manager should expose at least the following implementation-level APIs:

```python
def parse_port_expression(expression: str) -> list[int]:
    """Parse values such as 'all', '1-5,8', or '1,3,7-9' into explicit ports."""
```

```python
def validate_ports(ports: list[int], max_ports: int) -> None:
    """Validate uniqueness, generic syntax, and the platform-specific port limit."""
```

```python
def normalize_group_ports(
    group_name: str,
    ports: list[int],
) -> dict:
    """Convert explicit ports into normalized CONSOLE_SERVER_GROUP_PORT entries."""
```

```python
def validate_unique_label(port: int, label: str) -> None:
    """Validate reserved-label ownership and uniqueness against all other ports."""
```

```python
def validate_local_user_exists(username: str) -> None:
    """Validate the username against the configured Linux/NSS backend."""
```

```python
def set_port_config(port: int, updates: dict) -> None:
    """Validate and apply one or more port configuration updates."""
```

```python
def set_group_ports(group_name: str, expression: str) -> None:
    """Parse, validate, normalize, and replace a group's complete port mapping."""
```

```python
def write_transaction(operations: list) -> None:
    """Validate and atomically commit the ConfigDB operations."""
```

Additional label-specific helpers remain part of the same shared manager:

```python
def normalize_port_label(port: int, label: str | None) -> str:
    """Return COM<port> when a new-port label is missing or a label is explicitly blank."""
```

```python
def validate_reserved_port_label(
    port: int,
    label: str,
    max_ports: int,
) -> None:
    """Reject COM<M> when M is a valid port number different from port."""
```


```python
def set_user_config(
    username: str,
    password: str | None,
    role: str | None,
    groups: list[str] | None,
) -> None:
    """Create or update a console-server user and its non-secret metadata."""
```

Required behavior:

```text
Linux user does not exist, password missing:
    reject with CONSOLE_SERVER_PASSWORD_REQUIRED

Linux user does not exist, password supplied:
    create the Linux account and write non-secret ConfigDB metadata

Linux user exists, password omitted:
    keep the existing password unchanged and update supplied metadata

Linux user exists, password supplied:
    update the password and supplied metadata

Linux user exists but CONSOLE_SERVER_USER metadata is missing:
    create/import the missing ConfigDB metadata without recreating the Linux account
```


Linux account changes and ConfigDB updates are not one native atomic transaction. They must be coordinated using validation-before-write and compensating rollback, as defined in `console_server_user_management_implementation.md`.

The CLI and REST layers must not duplicate these parsing, normalization, validation, or transaction rules.

Detailed user creation, password update, deletion, non-secret metadata updates, and rollback behavior are specified in:

```text
console_server_user_management_implementation.md
```


---


Password-required error contract:

| Field | Value |
|---|---|
| CLI exit code | `1` |
| Error code | `CONSOLE_SERVER_PASSWORD_REQUIRED` |
| REST status | `400 Bad Request` |
| Error field | `password` |
| Message | `Password is required when creating a new user.` |

REST example:

```json
{
    "error": {
        "code": "CONSOLE_SERVER_PASSWORD_REQUIRED",
        "message": "Password is required when creating a new user.",
        "field": "password"
    }
}
```

## 14. Operational Command Integration

### 14.1 Show Sessions Command

For the first SONiC implementation, use the existing console-server runtime interface rather than mirroring session state into `STATE_DB`.

Recommended flow:

```text
show console-server sessions
        ↓
console-cli show sessions --json
        ↓
seriald socket/internal API
```

The SONiC `show` command acts as a wrapper and presentation layer.

It should:

1. invoke `console-cli show sessions --json`;
2. parse the JSON output;
3. format the result in SONiC CLI style;
4. return a nonzero exit status if the delegated command fails or returns invalid JSON.

This approach:

- reuses the existing console-server runtime API;
- avoids duplicating session state in `STATE_DB`;
- avoids synchronization and stale-data issues;
- keeps the first SONiC porting effort small;
- follows the pattern where a SONiC `show` command delegates to a specialized utility.

### 14.2 Data Source

`seriald` remains the authoritative source of active session information.

```text
seriald local session state
        ↓
seriald socket/internal API
        ↓
console-cli show sessions --json
        ↓
show console-server sessions
```

The SONiC show command must not parse human-readable console output. It must use the `--json` output as the machine-readable interface.

The JSON schema returned by `console-cli show sessions --json` becomes an internal compatibility contract between:

```text
seriald / console-cli
and
SONiC show console-server sessions
```

Changes to that JSON schema must be versioned or coordinated with the SONiC wrapper.

### 14.3 Failure Handling

The SONiC wrapper should handle:

| Failure | Required behavior |
|---|---|
| `console-cli` executable missing | Return error and nonzero exit status |
| `seriald` unavailable | Return error and nonzero exit status |
| Socket/API timeout | Return timeout error and nonzero exit status |
| Invalid JSON | Return internal data-format error |
| No active sessions | Return a valid empty result, not an error |

Example errors:

```text
Error: console server daemon is unavailable.
```

```text
Error: failed to retrieve console session information.
```

### 14.4 Connect Command

Keep the original connect implementation.

Recommended command:

```bash
connect line <port_number>
```

Recommended flow:

```text
connect line <port_number>
        ↓
existing console-cli connect implementation
        ↓
seriald socket/internal API
        ↓
interactive terminal session
```

Do not route interactive console traffic through `STATE_DB`.

Do not reimplement the terminal transport inside the SONiC wrapper if the existing `console-cli connect` path already provides the required behavior.

### 14.5 STATE_DB Decision

For the initial implementation:

```text
Do not publish console session information to STATE_DB.
```

`STATE_DB` integration may be considered later if independent consumers such as telemetry, REST, SNMP, or monitoring need persistent operational state.

If added later, it should be treated as a separate enhancement and should not change the existing interactive `connect` path.

### 14.6 Final Operational Command Decision

```text
1. seriald remains the authoritative source of session state.

2. show console-server sessions invokes:
   console-cli show sessions --json

3. console-cli obtains the data from the existing seriald
   socket/internal API.

4. The SONiC show command parses JSON and formats SONiC output.

5. connect line <port_number> keeps the original existing
   console-cli/seriald interactive implementation.

6. STATE_DB is not used for session display or interactive data
   in the first implementation.
```

