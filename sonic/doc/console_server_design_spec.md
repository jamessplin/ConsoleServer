# SONiC ConsoleServer Design Specification

**Target release:** SONiC 202511  
**Status:** Implemented; target hardware validation pending  
**Primary service:** `console-server.service`  
**Persistent configuration authority:** ConfigDB  
**Generated runtime configuration:** `/run/seriald/config.json`

---

# 1. Introduction

## 1.1 Purpose

This document specifies the architecture and design of the SONiC ConsoleServer integration for SONiC 202511.

The ConsoleServer provides centralized access to serial console ports attached to systems and network devices. The SONiC integration adds configuration, display, connection, validation, persistence, startup generation, and service lifecycle support while preserving the independent ConsoleServer application as a reusable, SONiC-agnostic application.

This specification defines:

- system boundaries and component responsibilities;
- configuration ownership and sources of truth;
- ConfigDB and YANG relationships;
- startup generation and service behavior;
- runtime update flows;
- user, group, port, session, and product-information handling;
- security and failure behavior;
- accepted limitations and future work.

The software baseline described here has passed a complete SONiC image build and root-filesystem verification. Hardware-dependent functional and performance results remain pending on the final target platform.

## 1.2 Scope

The specification covers:

- SONiC `config`, `show`, and `connect` command groups;
- the shared `sonic_console_server_manager` package;
- ConfigDB;
- `sonic-console-server.yang` and CVL validation for modeled configuration;
- `/usr/local/bin/console-server-config-generate`;
- `/etc/seriald/config.json` as bootstrap input;
- `/run/seriald/config.json` as generated runtime configuration;
- `console-server.service`;
- Linux/NSS account validation;
- the supported runtime-management interface `seriald-status`;
- package and image integration at an architectural level.

The SONiC startup sequence is:

```text
sonic.target
    ↓
console-server.service
    ↓
ExecStartPre=/usr/local/bin/console-server-config-generate
    ↓
sonic_console_server_manager.config_generate
    ↓
write /run/seriald/config.json
    ↓
ExecStart=/usr/local/bin/server.py
```

ConfigDB is the authority for SONiC-owned ConsoleServer configuration. `/etc/seriald/config.json` supplies bootstrap and platform-specific information that is not owned by ConfigDB. `/run/seriald/config.json` is generated runtime configuration and is not a persistent source of truth.

`/usr/local/bin/server.py` is the current executable path. Renaming it to `/usr/local/bin/serial-server.py` is future work.

## 1.3 Out of Scope

The following are maintained separately:

- exact CLI syntax, options, examples, and output;
- detailed test cases and procedures;
- source migration and porting steps;
- complete SONiC package-build instructions;
- branch, commit, pull-request, and milestone history;
- detailed operational recovery commands;
- resolved defect history.

Related documents:

- `console_server_cli_reference.md`;
- `console_server_test_plan.md`;
- `known_issues.md`;
- `SONiC_Package_Developer_Guide.md`;
- `SONiC_Utilities_ConsoleServer_Manager_Integration_Guide.md`, if retained.

## 1.4 Terminology

| Term | Meaning |
|---|---|
| Independent application | Standalone ConsoleServer application that does not depend on SONiC ConfigDB, YANG, CVL, or SONiC CLI modules |
| Bootstrap configuration | Persistent input file `/etc/seriald/config.json` |
| Runtime configuration | Generated file `/run/seriald/config.json` consumed by `console-server.service` |
| Linux/NSS | Authority for user-account existence and password state |
| Product information | Read-only limits such as `base_port`, `max_ports`, `max_users`, and `max_groups` |
| Runtime state | Active sessions, writer/observer state, client addresses, and timers |

---

# 2. Requirements and Design Goals

## 2.1 Functional Requirements

| Area | Requirement |
|---|---|
| Port configuration | Configure serial attributes, access mode, maximum clients, idle timeout, and label |
| Group configuration | Configure a ConsoleServer role and complete console-line membership |
| User configuration | Manage Linux/NSS users and non-secret ConsoleServer role/group metadata |
| Display | Show configured ports, groups, users, active sessions, and product information |
| Connection | Connect interactively by physical line or configured label |
| Persistence | Use the standard SONiC `config save` mechanism |
| Startup | Generate and validate `/run/seriald/config.json` before the runtime starts |
| Runtime update | Apply supported changes without restarting the complete service |
| Security | Keep passwords out of ConfigDB, runtime configuration, logs, and show output |

## 2.2 Platform Requirements

The design supports SONiC 202511 on ARM and x86 platforms.

Platform integration shall provide:

- physical console-port count;
- serial-device mappings;
- bootstrap configuration;
- product limits;
- device-specific `console_server.json`;
- package and service integration.

The current target product values are:

```text
Base TCP port: 35000
Console ports: 24
Maximum users: 16
Maximum groups: 16
```

These are platform or product values, not ordinary user-configurable fields.

## 2.3 Design Goals

1. Preserve the independent application's standalone Linux operation.
2. Use ConfigDB as the persistent authority for SONiC-owned configuration.
3. Keep Linux/NSS as the only authority for accounts and passwords.
4. Use YANG and CVL for modeled ConfigDB configuration.
5. Use supported, documented application interfaces rather than accessing private implementation components directly.
6. Generate runtime configuration deterministically and atomically.
7. Avoid duplicating live session state in STATE_DB.
8. Avoid storing per-line TCP ports while fixed sequential mapping is guaranteed.
9. Define rollback, compensation, and inconsistency windows explicitly.
10. Keep CLI, testing, known issues, and developer procedures in separate documents.

## 2.4 Non-Goals

The current design does not provide:

- REST or RESTCONF management;
- active-session publication to STATE_DB;
- configurable per-line TCP ports;
- one hard Redis transaction for all group rows;
- one atomic transaction spanning Linux/NSS and ConfigDB;
- CVL validation for the product-information cache;
- a persistent, manually edited `/run/seriald/config.json`;
- password ownership or persistence by the independent application.

---

# 3. Architecture and Ownership

## 3.1 System Context

```text
Normal management path

SONiC CLI
(config / show / connect)
        ↓
sonic_console_server_manager
        ├── read or update ConfigDB
        └── interact with the running ConsoleServer
            through seriald-status when required

Startup path

console-server.service
        ↓
console-server-config-generate
        ↓
sonic_console_server_manager.config_generate
        ├── read ConfigDB
        ├── read /etc/seriald/config.json
        └── validate referenced Linux/NSS users
        ↓
/run/seriald/config.json
        ↓
/usr/local/bin/server.py
```

The independent application owns the serial runtime. The SONiC integration owns SONiC-native configuration, validation, startup generation, service integration, and command integration.

## 3.2 Component Summary

| Component | Responsibility |
|---|---|
| SONiC CLI modules | Argument parsing, command registration, output formatting |
| `sonic_console_server_manager` | Shared validation, ConfigDB access, runtime coordination, session handling, and product-info handling |
| ConfigDB | Persistent SONiC-owned configuration and auxiliary product-info cache |
| YANG/CVL | Validation of modeled ConsoleServer ConfigDB tables |
| `console-server-config-generate` | Startup merge, validation, and atomic runtime-file generation |
| `/etc/seriald/config.json` | Bootstrap and platform-specific persistent input |
| `/run/seriald/config.json` | Generated runtime configuration |
| `console-server.service` | Startup sequencing and runtime supervision |
| `server.py` | Serial devices, listeners, access enforcement, and sessions |
| `seriald-status` | Supported interface for live runtime management and status operations |
| Linux/NSS | User accounts and passwords |

## 3.3 Ownership Matrix

| Information | Authority |
|---|---|
| Port configuration | ConfigDB |
| ConsoleServer groups and memberships | ConfigDB |
| Non-secret user role/group metadata | ConfigDB |
| User-account existence and password state | Linux/NSS |
| Bootstrap and platform-specific values | `/etc/seriald/config.json` |
| Generated runtime configuration | `/run/seriald/config.json` |
| Live sessions and writer/observer state | Running ConsoleServer application |
| Product-information source | Read-only product data exposed by the running ConsoleServer |
| Product-information cache | `CONSOLE_SERVER_PRODUCT_INFO\|global` |

## 3.4 Boundary Rules

- The independent application shall not directly depend on SONiC libraries.
- SONiC CLI modules shall use the shared manager instead of duplicating logic.
- ConfigDB shall not store passwords or live sessions.
- `/run/seriald/config.json` shall remain a generated output.
- Linux/NSS shall remain the only account and password authority.
- Session state shall remain runtime-owned.
- Product information shall remain read-only to SONiC users.
- The SONiC manager shall use `seriald-status` for supported live runtime management and status operations.

---

# 4. Configuration Data Model

## 4.1 YANG-Modeled Tables

| Table | Key | Purpose |
|---|---|---|
| `CONSOLE_SERVER_PORT` | port number | Per-line serial and access configuration |
| `CONSOLE_SERVER_GROUP` | group name | Group role and parent definition |
| `CONSOLE_SERVER_GROUP_PORT` | group, port | Group membership |
| `CONSOLE_SERVER_USER` | username | Non-secret user role metadata |
| `CONSOLE_SERVER_USER_GROUP` | username, group | User-to-group membership |

These tables are modeled in `sonic-console-server.yang` and are subject to supported YANG/CVL validation.

## 4.2 Auxiliary Product-Information Cache

The manager uses:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
```

as a ConfigDB read-through cache.

Normalized fields are:

```text
base_port
max_ports
max_users
max_groups
```

This cache is not represented in `sonic-console-server.yang` and is therefore not CVL validated. The manager validates cached and live values before use.

## 4.3 Important Validation Rules

- Generic schema port range may exceed the platform's physical port count.
- The manager enforces the actual product limit.
- Idle timeout range is `0..86400`; `0` disables the timeout.
- Labels must be unique.
- Default or reserved labels follow `COM<port>` ownership rules.
- Group membership must reference valid initialized console lines.
- User group names must exist.
- Product-info values must be integers and internally consistent.
- The TCP range must satisfy:

```text
base_port + max_ports <= 65535
```

## 4.4 Data Not Stored in ConfigDB

ConfigDB does not store:

- passwords or password hashes;
- active sessions;
- writer or observer runtime assignment;
- client IP addresses or ports;
- idle countdown state;
- generated runtime configuration;
- per-line TCP ports under the current fixed mapping.

---

# 5. Startup and Runtime Behavior

## 5.1 Service Startup

```text
sonic.target
    ↓
console-server.service
    ↓
ExecStartPre=console-server-config-generate
    ↓
read bootstrap + ConfigDB
    ↓
validate Linux/NSS user references
    ↓
write /run/seriald/config.json atomically
    ↓
ExecStart=/usr/local/bin/server.py
```

In SONiC:

```text
console-server.service: enabled
seriald.service: disabled
```

The two services shall not run simultaneously because they would compete for the same serial devices and TCP listeners.

## 5.2 Startup Merge Policy

| Object | Startup behavior |
|---|---|
| Ports | ConfigDB values override SONiC-owned fields in matching bootstrap lines |
| Groups | ConfigDB groups replace bootstrap group definitions |
| Managed users | Apply ConfigDB role/group metadata only when the Linux/NSS user exists |
| Users created outside ConfigDB | Preserve the existing Linux account, password, and group membership unchanged |
| Passwords | Never read, copied, generated, modified, emitted, or logged |
| Product information | Not retrieved as part of startup generation in the current implementation |

The generator shall validate the complete candidate configuration before replacing the runtime file.

## 5.3 Runtime File Behavior

`/run/seriald/config.json`:

- is written atomically;
- uses mode `0600`;
- is consumed by `server.py`;
- is regenerated when the service starts;
- is not used by `config save`;
- is not written back to `/etc/seriald/config.json`.

Normal live updates do not rewrite this file. Therefore, after runtime changes, the file may continue to represent the startup snapshot until the next service restart.

## 5.4 Port Update Flow

```text
validate request
    ↓
apply runtime update through seriald-status
    ↓
write ConfigDB
    ↓
rollback runtime if ConfigDB write fails
```

No-op requests shall succeed without unnecessary runtime or ConfigDB changes.

## 5.5 Group Update Flow

```text
validate complete candidate group
    ↓
apply one runtime group update
    ↓
write ConfigDB group parent and membership rows sequentially
    ↓
compensate runtime if ConfigDB write fails
```

The ConfigDB rows are not committed through one hard Redis transaction.

## 5.6 User Update Flow

```text
validate ConsoleServer metadata
    ↓
perform supported Linux/NSS user operation
    ↓
write ConfigDB role/group metadata
```

Linux/NSS owns accounts and passwords. ConfigDB stores only non-secret metadata.

No atomic transaction spans Linux/NSS changes and ConfigDB metadata.

## 5.7 Session Display Flow

```text
show console-server sessions
    ↓
SONiC show module
    ↓
sonic_console_server_manager
    ↓
query the running ConsoleServer through the supported status interface
    ↓
validate and normalize the returned data
    ↓
convert nested per-line clients into one row per active client
    ↓
display
```

Lines with no clients do not produce display rows. Session state is not persisted in ConfigDB or STATE_DB.

## 5.8 Product-Information Flow

```text
read CONSOLE_SERVER_PRODUCT_INFO|global
        ↓
valid cache?
    ├── yes → return cached values
    └── no  → query the authoritative product-information source
               ↓
              validate and normalize
               ↓
              best-effort cache update
               ↓
              return live values
```

Product information is read-only from the SONiC user perspective.

## 5.9 Persistence Flow

```text
config console-server ...
    ↓
ConfigDB updated
    ↓
config save
    ↓
/etc/sonic/config_db.json
    ↓
reboot
    ↓
ConfigDB restored
    ↓
console-server.service regenerates runtime configuration
```

No feature-specific save command is required.

---

# 6. Security, Failure Handling, and Limitations

## 6.1 Password Handling

- Linux/NSS is the only authority for password state.
- Passwords and password hashes shall not be stored in ConfigDB.
- Passwords shall not be written into `/run/seriald/config.json`.
- Passwords shall not appear in show output, logs, or exceptions.
- External commands shall be invoked with an argument list and `shell=False`.

A password passed through process arguments may still be briefly visible to privileged process inspection. Eliminating this requires a future stdin, file-descriptor, or Unix-socket interface.

## 6.2 Startup Failure

If startup generation or validation fails:

- the new runtime file shall not replace the previous valid file;
- `console-server.service` shall not start;
- the failure shall be logged without exposing secrets.

## 6.3 Runtime Update Failure

| Operation | Failure behavior |
|---|---|
| Port | Attempt runtime rollback if ConfigDB write fails |
| Group | Attempt runtime compensation; ConfigDB rows may be partially updated |
| User | Manual recovery may be required if Linux/NSS succeeds and ConfigDB fails |
| Product cache | Return validated live values even if cache write fails |
| Session query | Return a clear error if runtime JSON is malformed or unavailable |

## 6.4 Accepted Limitations

- Group ConfigDB writes are sequential rather than one hard transaction.
- User operations are not atomic across Linux/NSS and ConfigDB.
- Product-info cache is not CVL validated.
- Session display depends on the live independent-application interface.
- TCP mapping assumes `tcp_port = base_port + line`.
- Runtime configuration file may lag live runtime state after updates.
- CLI startup performance is pending validation on final target hardware.

Detailed recovery procedures and current operational issues belong in `known_issues.md`.

---

# 7. Related Documents and Future Work

## 7.1 Related Documents

| Document | Purpose |
|---|---|
| `console_server_cli_reference.md` | Exact commands, options, examples, and output |
| `console_server_test_plan.md` | Detailed test procedures and acceptance criteria |
| `known_issues.md` | Current limitations, deferred improvements, and recovery guidance |
| `SONiC_Package_Developer_Guide.md` | SONiC package and image integration |
| `SONiC_Utilities_ConsoleServer_Manager_Integration_Guide.md` | Developer porting and sonic-utilities integration, if retained |

## 7.2 Future Work

- Rename `/usr/local/bin/server.py` to `/usr/local/bin/serial-server.py` and update packaging, service files, tests, and documentation.
- Re-measure command latency on the final target hardware.
- Consider secure password transport that does not use process arguments.
- Consider stronger Redis transaction handling if group-write atomicity becomes necessary.
- Revisit the fixed sequential TCP-port model if per-line ports become configurable.
- Review whether the product-info cache requires explicit refresh or versioning policy.

---

# 8. Design Summary

The SONiC ConsoleServer integration separates four forms of state:

```text
ConfigDB
    persistent SONiC-owned configuration

Linux/NSS
    user accounts and passwords

/run/seriald/config.json
    generated startup configuration

Running ConsoleServer application
    live serial devices, listeners, and sessions
```

This separation preserves the standalone application boundary while providing SONiC-native configuration, validation, persistence, startup sequencing, and command integration.
