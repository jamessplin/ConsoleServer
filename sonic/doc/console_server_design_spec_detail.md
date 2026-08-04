# 1. Introduction

## 1.1 Purpose

This document specifies the architecture and design of the SONiC ConsoleServer integration for SONiC 202511.

The ConsoleServer provides centralized access to the serial console ports of attached systems and network devices. The SONiC integration adds configuration, display, connection, persistence, validation, startup generation, and service-lifecycle support while preserving the independent ConsoleServer application as a reusable, SONiC-agnostic application.

This specification defines:

* component responsibilities and system boundaries;
* configuration ownership and sources of truth;
* ConfigDB and runtime data models;
* startup generation and service lifecycle;
* runtime update and synchronization behavior;
* user, group, port, session, and product-information handling;
* validation and security requirements;
* persistence, failure handling, and recovery principles;
* design constraints, trade-offs, and known limitations.

It describes the implemented software baseline that has passed a complete SONiC image build and root-filesystem verification. Hardware-dependent functional and performance results remain subject to validation on the final target platform.

## 1.2 Scope

This specification covers the integration of the ConsoleServer application with the following SONiC components:

* SONiC `config`, `show`, and `connect` command groups;
* the shared `sonic_console_server_manager` Python package;
* ConfigDB;
* the `sonic-console-server.yang` model and CVL validation for modeled configuration;
* the `console-server-config-generate` startup generator;
* `/etc/seriald/config.json` as the read-only bootstrap configuration;
* `/run/seriald/config.json` as the generated runtime configuration;
* `console-server.service`;
* Linux/NSS user-account validation;
* the independent application interfaces `console-cli` and `seriald-status`;
* Debian packaging and SONiC image integration at an architectural level.

The SONiC service startup sequence is:

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

During startup generation, the generator reads:

```text
ConfigDB
/etc/seriald/config.json
```

It also checks Linux/NSS to verify that users referenced by ConsoleServer metadata exist.

ConfigDB does not start the service. It is a configuration source read by the generator after systemd starts `console-server.service`.

ConfigDB is authoritative for SONiC-owned ConsoleServer configuration. `/etc/seriald/config.json` supplies bootstrap and platform-specific information that is not owned by ConfigDB.

`/run/seriald/config.json` is the generated runtime configuration consumed by `console-server.service`. It is recreated from persistent inputs and is not itself a persistent configuration authority.
`/usr/local/bin/server.py` is the current implemented executable path. Renaming it to `/usr/local/bin/serial-server.py` is a future implementation task and shall not be described as current behavior.

## 1.3 Out of Scope

The following material is maintained in separate documents and is not duplicated in this specification:

* exact CLI syntax, command options, examples, and output formatting;
* detailed test cases, test identifiers, procedures, and expected results;
* source migration and porting procedures;
* complete SONiC package-build instructions;
* branch names, commit identifiers, pull-request status, and temporary project milestones;
* historical defect lists;
* detailed operational recovery commands.

The related documents are:

* `console_server_cli_reference.md`;
* `console_server_test_plan.md`;
* `known_issues.md`;
* `SONiC_Package_Developer_Guide.md`;
* `SONiC_Utilities_ConsoleServer_Manager_Integration_Guide.md`, if retained as a separate developer guide.

The Design Specification defines architecture and behavior.

The CLI Reference defines exact commands, options, examples, and output.

The Test Plan defines detailed verification procedures.

Known Issues records current limitations, deferred improvements, and recovery guidance.

Developer guides describe package integration and porting workflows.

## 1.4 Intended Audience

This specification is intended for:

* SONiC developers;
* ConsoleServer application developers;
* platform and image integrators;
* code reviewers and maintainers;
* system validation engineers;
* technical support and sustaining teams.

Readers are expected to understand basic SONiC concepts, including ConfigDB, YANG, CVL, systemd services, Debian packaging, and the standard SONiC configuration-persistence model.

## 1.5 Terminology

### ConsoleServer

The complete serial-console management feature, including the independent application and its SONiC integration.

### Independent application

The standalone ConsoleServer implementation that can operate outside SONiC.

It exposes public command interfaces such as:

```text
/usr/local/bin/console-cli
/usr/local/bin/seriald-status
```

The independent application does not directly depend on SONiC ConfigDB, YANG, CVL, or SONiC CLI modules.

### Console line

A physical serial port managed by the ConsoleServer.

### Bootstrap configuration

The persistent file:

```text
/etc/seriald/config.json
```

It contains application defaults and platform-specific information that is not completely represented in ConfigDB.

SONiC reads but does not write this file.

### Runtime configuration

The generated file:

```text
/run/seriald/config.json
```

It is constructed from ConfigDB and `/etc/seriald/config.json`.

During generation, users referenced by ConsoleServer metadata are checked against Linux/NSS.

The file is consumed by `console-server.service` and may be recreated during startup or service restart.

### Runtime snapshot

Another term for `/run/seriald/config.json`, emphasizing that it is a generated point-in-time representation of the configuration used by the running service.

### Linux/NSS

The Linux account and name-service system used as the authoritative source for user-account existence and password state.

Linux/NSS owns accounts and passwords.

ConfigDB stores only non-secret ConsoleServer metadata, such as ConsoleServer role and ConsoleServer group memberships.

The independent application does not persist account or password state.

### Product information

Read-only ConsoleServer limits and platform values, including:

```text
base_port
max_ports
max_users
max_groups
```

The SONiC manager uses the following ConfigDB entry as a read-through cache:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
```

The cache is not represented in `sonic-console-server.yang` and is therefore not validated by CVL.

Cached and live product information is validated by the manager before use.

Product information is retrieved at runtime when a SONiC command or manager operation requires it. It is not user-configurable through the SONiC ConsoleServer CLI.

### Persistent configuration

Configuration stored in ConfigDB and preserved through the standard SONiC `config save` mechanism.

### Runtime state

Transient information maintained by the running application, such as:

* active client sessions;
* writer and observer roles;
* client addresses;
* idle timers;
* remaining session time.

Runtime session state is queried from the independent application and is not copied into STATE_DB in the current implementation.

### ConsoleServer role

The access role associated with a ConsoleServer group or user.

The term `ConsoleServer role` is used consistently throughout this document to distinguish this attribute from unrelated Linux or SONiC roles.

## 1.6 Document Conventions

The terms **must**, **shall**, and **required** identify mandatory behavior.

The terms **should** and **recommended** identify preferred behavior that may have an accepted alternative.

The terms **may** and **optional** identify permitted but non-mandatory behavior.

Paths and command names are shown in monospace, for example:

```text
/usr/local/bin/console-server-config-generate
```

Current implemented behavior is described in the present tense.

Planned changes and deferred improvements are explicitly identified as future work.

---

# 2. Requirements and Design Goals

## 2.1 Functional Requirements

The SONiC ConsoleServer integration shall provide the following functional areas.

### 2.1.1 Port configuration

The system shall support configuration of each physical console line, including:

* baud rate;
* data bits;
* parity;
* stop bits;
* flow control;
* access mode;
* maximum clients;
* idle timeout;
* line label.

Port configuration shall be represented in ConfigDB and validated before being applied to the runtime.

The physical serial-device or interface association is platform-defined and is not configurable through the SONiC ConsoleServer CLI.

### 2.1.2 Group configuration

The system shall support named ConsoleServer groups that associate:

* ConsoleServer role;
* one or more console lines.

Group updates shall operate on the complete candidate group definition.

Updating an existing group shall replace its complete ConsoleServer role and membership set rather than incrementally preserving omitted membership entries.

### 2.1.3 User configuration and metadata

The system shall support configuration of Linux/NSS users for ConsoleServer access.

Linux/NSS shall remain authoritative for:

* user-account existence;
* password state.

The system shall support non-secret ConsoleServer metadata for those users, including:

* ConsoleServer role;
* ConsoleServer group memberships.

ConfigDB shall store only non-secret ConsoleServer metadata.

ConfigDB shall not store:

* passwords;
* password hashes;
* other authentication secrets.

The independent application shall not persist user-account or password state.

Passwords may be configured through the supported user-management command flow, but the resulting credential shall remain owned and stored by Linux/NSS.

### 2.1.4 Display and operational visibility

The system shall display:

* configured console-line settings;
* configured ConsoleServer groups;
* configured non-secret user metadata, including ConsoleServer role and ConsoleServer group memberships;
* active console sessions reported by the running ConsoleServer application;
* read-only product information.

Configuration-backed displays shall read ConfigDB where appropriate.

User passwords shall not be displayed by SONiC show commands.

Active session information shall be retrieved from the running ConsoleServer application through:

```text
console-cli show sessions --json
```

Product information shall be obtained from the manager’s validated ConfigDB read-through cache or, when the cache is missing or invalid, from:

```text
console-cli show product-info --json
```

Session information and product information are read-only operational information. They are not user-configurable through the SONiC ConsoleServer CLI.

### 2.1.5 Interactive connection

The system shall support interactive connection to a console line by:

* physical line number;
* configured line label.

Label lookup shall use the configured label and follow the documented case-sensitivity and uniqueness rules.

### 2.1.6 Persistence

The system shall use the standard SONiC persistence mechanism:

```text
config save
```

No ConsoleServer-specific save command shall be required.

Persistent ConsoleServer configuration shall be restored from ConfigDB after reboot.

The generated runtime configuration shall be reconstructed during service startup.

### 2.1.7 Startup generation

The startup generator shall:

1. read `/etc/seriald/config.json` as the bootstrap template;
2. read SONiC-owned port, group, and user metadata from ConfigDB;
3. override SONiC-owned port fields with ConfigDB values;
4. replace bootstrap group definitions with ConfigDB group definitions;
5. apply ConfigDB ConsoleServer role and group metadata only to users that exist in Linux/NSS;
6. preserve bootstrap users that are not managed by ConfigDB, subject to valid ConsoleServer group memberships;
7. verify that the generated configuration is structurally valid and that its ports, labels, groups, memberships, and referenced users satisfy the implemented constraints;
8. atomically write `/run/seriald/config.json`;
9. prevent `console-server.service` from starting if generation or validation fails.

The generator shall not:

* read user passwords;
* generate user passwords;
* copy user passwords;
* modify user passwords;
* write user passwords to the runtime configuration;
* log user passwords.

The generated file shall be owned by root and written with mode `0600`.

Product information is not retrieved as part of startup generation in the current implementation.

### 2.1.8 Runtime configuration updates

Normal configuration commands shall update the running application through the independent application’s supported public interfaces.

The system shall avoid restarting the complete ConsoleServer service for ordinary port, group, or user configuration changes when a supported runtime update interface exists.

Requests that do not change the current configuration shall succeed without unnecessary runtime or ConfigDB updates.

### 2.1.9 Session visibility

The system shall retrieve live session data using:

```text
console-cli show sessions --json
```

The manager shall:

1. execute the independent application command;
2. verify that the returned data is valid JSON;
3. verify that the expected line and client structures are present;
4. convert nested per-line client lists into one display record per active client;
5. copy applicable line-level information, such as line number and access mode, into each client record.

For example:

```text
line 1
    client A
    client B
```

is displayed as:

```text
line 1, client A
line 1, client B
```

Lines with no active clients shall not produce session rows.

Session information shall not be persisted in ConfigDB or STATE_DB.

### 2.1.10 Product information

The system shall retrieve and validate read-only product information when a runtime SONiC command or manager operation requires it.

The manager shall use:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
```

as a ConfigDB read-through cache.

The runtime behavior shall be:

```text
read CONSOLE_SERVER_PRODUCT_INFO|global
        ↓
valid cache?
    ├── yes → return cached values
    └── no  → run console-cli show product-info --json
               ↓
              validate and normalize
               ↓
              attempt a best-effort cache update
               ↓
              return validated live values
```

The cache shall contain normalized values for:

```text
base_port
max_ports
max_users
max_groups
```

A valid cache entry may be returned immediately.

A missing, incomplete, or invalid cache entry shall cause the manager to:

1. call `console-cli show product-info --json`;
2. verify that the response is a JSON object;
3. normalize the application field names;
4. validate the values;
5. attempt a best-effort ConfigDB cache update;
6. return the validated live information even if the cache write fails.

The product-info cache is not defined in `sonic-console-server.yang`.

It is therefore not validated by CVL.

All cached and live product-information values shall be validated by the ConsoleServer manager before use.

## 2.2 Platform Requirements

The integration shall support the SONiC 202511 software base on both ARM and x86 platforms.

Platform-specific integration shall provide:

* physical console-port count;
* serial-device mappings;
* bootstrap configuration;
* product limits;
* device-specific `console_server.json`;
* required service and package integration.

The generic YANG port range may be broader than the number of physical console lines available on a specific platform.

Runtime and manager validation shall enforce the actual product limit reported for that platform.

The current target hardware is ARM-based, but the software design and implementation are not limited to ARM.

The current target product values are:

```text
Base TCP port: 35000
Console ports: 24
Maximum users: 16
Maximum groups: 16
```

These values are platform or product information and shall not be treated as ordinary user-configurable fields.

## 2.3 Design Goals

### 2.3.1 Preserve application independence

The independent ConsoleServer application shall remain usable outside SONiC.

SONiC-specific behavior shall be implemented through:

* SONiC CLI integration modules;
* the shared SONiC manager;
* ConfigDB and YANG integration;
* the startup generator;
* SONiC service integration;
* SONiC package integration.

The independent application shall not directly depend on SONiC libraries, ConfigDB, YANG, or CVL.

### 2.3.2 Establish clear ownership

Each type of information shall have a clearly defined authority.

| Information                                   | Authority                         |         |
| --------------------------------------------- | --------------------------------- | ------- |
| SONiC-owned port configuration                | ConfigDB                          |         |
| ConsoleServer group configuration             | ConfigDB                          |         |
| Non-secret ConsoleServer user metadata        | ConfigDB                          |         |
| User-account existence and password state     | Linux/NSS                         |         |
| Bootstrap and platform-specific configuration | `/etc/seriald/config.json`        |         |
| Generated runtime configuration               | `/run/seriald/config.json`        |         |
| Live session state                            | Running ConsoleServer application |         |
| Product-information source                    | Independent application           |         |
| Product-information cache                     | `CONSOLE_SERVER_PRODUCT_INFO      | global` |

The generated runtime file shall not become a second persistent configuration authority.

### 2.3.3 Preserve standard SONiC behavior

The integration shall use standard SONiC mechanisms wherever practical, including:

* ConfigDB;
* YANG and CVL for modeled configuration;
* the standard `config save` workflow;
* `sonic.target`;
* Debian package installation;
* established `config`, `show`, and `connect` command structures.

### 2.3.4 Avoid secret duplication

Passwords and password hashes shall not be stored in:

* ConfigDB;
* `/run/seriald/config.json`;
* show-command output;
* log messages;
* exception messages.

Only Linux/NSS shall persist password state.

### 2.3.5 Generate deterministic runtime configuration

Given the same valid bootstrap configuration, ConfigDB state, and Linux/NSS user-account state, the generator should produce the same effective runtime configuration.

Repeated generation shall be idempotent and shall not silently change persistent inputs.

### 2.3.6 Fail safely during startup

A validation or generation failure shall not replace an existing valid runtime configuration with a partial or invalid file.

`console-server.service` shall not start if startup generation fails.

The runtime file shall be replaced atomically only after the new candidate configuration is successfully generated and validated.

### 2.3.7 Apply runtime changes efficiently

Ordinary configuration updates should use the independent application’s runtime interfaces rather than restarting all console lines.

Requests that do not change the current configuration should not cause unnecessary:

* runtime update commands;
* ConfigDB writes;
* rollback processing;
* service restarts.

Only changed fields should be applied where supported.

### 2.3.8 Minimize duplicated state

Live session state shall remain owned by the running application and shall not be mirrored into STATE_DB.

TCP ports shall be derived from the product base port and console line while the application guarantees fixed sequential mapping:

```text
tcp_port = base_port + line
```

Per-line TCP ports shall not be stored redundantly in ConfigDB under the current design.

### 2.3.9 Provide explicit failure behavior

Operations that span more than one subsystem shall define:

* validation order;
* update order;
* rollback or compensation behavior;
* possible inconsistency windows;
* recovery responsibility.

The implementation shall not imply stronger atomicity than it provides.

### 2.3.10 Maintain reviewable component boundaries

Shared logic for the following functions shall reside in `sonic_console_server_manager`:

* validation;
* ConfigDB access;
* runtime command execution;
* port-expression parsing;
* group handling;
* label validation;
* session retrieval;
* product-information handling;
* startup configuration generation.

SONiC CLI modules shall call the shared manager rather than duplicating this logic.

## 2.4 Non-Goals

The current design does not attempt to provide the following.

### 2.4.1 REST API

A REST or RESTCONF management interface is not part of the current implementation.

### 2.4.2 STATE_DB session publication

Active session state is not copied into STATE_DB.

Session display depends on the independent application’s live interface.

### 2.4.3 Configurable per-line TCP ports

The current design assumes:

```text
tcp_port = base_port + line
```

A future implementation with configurable per-line TCP ports would require changes to:

* schema;
* manager logic;
* display logic;
* runtime interfaces.

### 2.4.4 Hard Redis transaction for group metadata

Group metadata may span:

```text
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
```

The current implementation writes these ConfigDB entries sequentially rather than through one hard Redis transaction.

Runtime compensation is attempted when ConfigDB updates fail, but previously written ConfigDB rows are not guaranteed to roll back as one atomic unit.

### 2.4.5 Cross-system atomic user transaction

No atomic transaction spans Linux/NSS account changes and ConfigDB user metadata.

For example:

```text
Linux/NSS account operation succeeds
        ↓
ConfigDB metadata write fails
```

Automatic rollback is not always safe because the previous password or complete Linux account state may not be available.

### 2.4.6 Password ownership by the independent application

The independent application does not own or persist Linux accounts or passwords.

Linux/NSS remains the authoritative source for user accounts and password state.

### 2.4.7 Persistent runtime file

`/run/seriald/config.json` is not intended to be manually edited or used as persistent configuration.

Direct edits may be overwritten during:

* service restart;
* startup generation;
* reboot.

### 2.4.8 Product-information CVL validation

`CONSOLE_SERVER_PRODUCT_INFO|global` is not modeled in `sonic-console-server.yang`.

CVL therefore does not validate this cache.

Validation is performed by the ConsoleServer manager before cached or live values are used.

### 2.4.9 Service executable rename

Renaming:

```text
/usr/local/bin/server.py
```

to:

```text
/usr/local/bin/serial-server.py
```

is a future cleanup task and is not part of the current implemented design.

## 2.5 Design Principles

The implementation follows these principles:

1. Use one persistent authority for each type of data.
2. Validate requests before modifying state whenever possible.
3. Do not expose or duplicate secrets.
4. Use public independent-application interfaces rather than internal implementation details.
5. Preserve standalone application portability.
6. Use standard SONiC persistence and service mechanisms.
7. Treat generated runtime files as replaceable outputs.
8. Describe limitations explicitly instead of implying unsupported atomicity.
9. Keep architecture, command reference, testing, known issues, and developer procedures in separate documents.
10. Treat the current source code and validated image as authoritative when older documents conflict.

---

# 3. System Context and Component Boundaries

## 3.1 System Context

The SONiC ConsoleServer solution consists of two major parts:

1. the independent ConsoleServer application; and
2. the SONiC integration layer.

The independent application provides the serial-console runtime and public interfaces needed to configure and inspect that runtime. It is designed to operate on a standalone Linux system without depending on SONiC.

The SONiC integration layer adds:

- SONiC `config`, `show`, and `connect` commands;
- ConfigDB persistence;
- YANG and CVL validation for modeled configuration;
- startup configuration generation;
- systemd service integration;
- package and image integration.

The SONiC integration shall use the independent application through its supported external interfaces. It shall not duplicate the independent application's serial-console runtime implementation.

## 3.2 SONiC Components

### 3.2.1 SONiC CLI modules

The SONiC CLI integration provides these command groups:

```text
config console-server ...
show console-server ...
connect console-server ...
```

The CLI modules are responsible for:

- parsing command arguments;
- presenting user-facing output and errors;
- invoking the shared `sonic_console_server_manager` APIs.

The CLI modules shall not duplicate ConfigDB access, validation, runtime execution, session parsing, product-information handling, or startup-generation logic.

Exact command syntax, options, examples, and output formats are defined in `console_server_cli_reference.md`.

### 3.2.2 `sonic_console_server_manager`

`sonic_console_server_manager` is the shared SONiC implementation layer.

It provides:

- ConfigDB access;
- validation of port, group, user, label, and product-information values;
- port-expression parsing and normalization;
- group and membership handling;
- runtime command execution;
- session retrieval and normalization;
- product-information read-through caching;
- startup configuration generation.

The manager separates SONiC-specific behavior from the independent ConsoleServer application.

When invoking an external command, the manager shall pass the executable and arguments as an argument list and shall not enable a command shell. The current implementation uses `subprocess.run()` with its default effective setting of `shell=False`.

This prevents shell interpretation of user-supplied values and reduces command-injection and quoting risks.

The use of `shell=False` does not eliminate the separate risk that a password passed through process arguments may be briefly visible to privileged process inspection. That limitation is documented separately.

### 3.2.3 ConfigDB

ConfigDB is the persistent authority for SONiC-owned ConsoleServer configuration.

It stores:

- console-line configuration;
- ConsoleServer group definitions;
- ConsoleServer group memberships;
- non-secret ConsoleServer user metadata.

ConfigDB does not store:

- passwords;
- password hashes;
- live session state;
- the generated startup configuration file.

The standard SONiC `config save` operation persists ConfigDB into the saved SONiC configuration.

ConfigDB also contains the manager-owned product-information read-through cache:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
```

This cache is not part of `sonic-console-server.yang` and is not validated by CVL. The ConsoleServer manager validates cached values before using them.

### 3.2.4 YANG and CVL

`sonic-console-server.yang` defines the ConfigDB schema and constraints for modeled ConsoleServer configuration.

The modeled configuration includes:

```text
CONSOLE_SERVER_PORT
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
CONSOLE_SERVER_USER
CONSOLE_SERVER_USER_GROUP
```

YANG and CVL validate supported constraints for these tables before ConfigDB updates are accepted through normal SONiC configuration paths.

The following data is outside the ConsoleServer YANG model:

- `CONSOLE_SERVER_PRODUCT_INFO|global`;
- live session state;
- Linux/NSS account and password state;
- `/etc/seriald/config.json`;
- `/run/seriald/config.json`.

Those items are validated or managed by their owning components rather than by ConsoleServer CVL rules.

### 3.2.5 `console-server-config-generate`

`/usr/local/bin/console-server-config-generate` is the executable invoked by `console-server.service` before the runtime starts.

It calls:

```text
sonic_console_server_manager.config_generate
```

The generator:

1. reads `/etc/seriald/config.json` as the bootstrap template;
2. reads SONiC-owned port, group, and user metadata from ConfigDB;
3. applies ConfigDB-owned values to the in-memory candidate configuration;
4. verifies that users referenced by ConfigDB metadata exist in Linux/NSS;
5. validates the generated candidate configuration;
6. atomically writes `/run/seriald/config.json`.

The generator does not retrieve product information in the current implementation.

The generator shall not read, generate, copy, modify, write, or log user passwords.

### 3.2.6 `console-server.service`

`console-server.service` is the SONiC-owned systemd service for the ConsoleServer runtime.

It is enabled under:

```text
sonic.target
```

The service startup control flow is:

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

Systemd starts and controls `console-server.service`.

During `ExecStartPre`, the generator reads ConfigDB and `/etc/seriald/config.json`. ConfigDB is a configuration input; it is not part of the systemd service-control path.

If startup generation fails, systemd shall not execute `/usr/local/bin/server.py`.

The standalone `seriald.service` is disabled in the SONiC image to avoid conflicting service ownership.

### 3.2.7 `/run/seriald/config.json`

`/run/seriald/config.json` is the generated startup configuration consumed by `/usr/local/bin/server.py`.

It is created before `server.py` starts.

The file is not the source for `config save`. Persistent ConsoleServer configuration is saved from ConfigDB through the standard SONiC persistence mechanism.

After startup:

- normal port, group, and user changes are applied to the running ConsoleServer through supported runtime interfaces;
- the corresponding persistent SONiC-owned configuration is updated in ConfigDB;
- `server.py` does not write those changes back to `/run/seriald/config.json`;
- the file may therefore continue to represent the configuration generated at service startup.

The file is regenerated from `/etc/seriald/config.json` and ConfigDB when `console-server.service` starts again.

The generator shall replace the file atomically and write it with owner-only permissions, mode `0600`.

### 3.2.8 `/etc/seriald/config.json`

`/etc/seriald/config.json` provides bootstrap and platform-specific configuration used during startup configuration generation.

It may contain:

- platform serial-device mappings;
- independent-application defaults;
- settings that are not modeled as SONiC-owned ConfigDB fields.

SONiC reads this file but does not write back to it.

ConfigDB remains authoritative for SONiC-owned ConsoleServer configuration.

### 3.2.9 Linux/NSS

Linux/NSS is authoritative for:

- user-account existence;
- password state.

During startup generation, Linux/NSS is consulted only to verify that users referenced by ConsoleServer metadata exist.

Linux/NSS is not a source of port, group, or serial configuration, and its password data is not copied into `/run/seriald/config.json`.

ConfigDB stores only non-secret ConsoleServer metadata for those users, such as ConsoleServer role and ConsoleServer group memberships.

### 3.2.10 Independent application boundary

The independent ConsoleServer application owns:

- the serial-console runtime;
- active client sessions;
- writer and observer state;
- runtime connection state;
- public runtime and status interfaces used by the SONiC manager.

Standalone commands such as `console-cli` and `seriald-status` belong to the independent application. They are not SONiC-owned components and therefore do not have separate component subsections in this specification.

Where relevant, this specification describes only how the SONiC manager interacts with those external interfaces.

## 3.3 Component Interaction

### 3.3.1 Startup control flow

```text
sonic.target
    ↓
console-server.service
    ↓
console-server-config-generate
    ↓
sonic_console_server_manager.config_generate
    ↓
/run/seriald/config.json
    ↓
/usr/local/bin/server.py
```

### 3.3.2 Startup data flow

```text
/etc/seriald/config.json ───────┐
                               │
ConfigDB ──────────────────────┼──→ config_generate
                               │
Linux/NSS user existence ─────┘        │
                                        ↓
                              /run/seriald/config.json
```

Linux/NSS provides a validation result, not configuration data for the generated file.

Product information is not part of the current startup-generation data flow.

### 3.3.3 Runtime configuration flow

```text
SONiC config command
        ↓
SONiC CLI module
        ↓
sonic_console_server_manager
        ├──→ validate request
        ├──→ update running ConsoleServer
        └──→ update ConfigDB
```

Requests that do not change the existing configuration should succeed without unnecessary runtime commands or ConfigDB writes.

### 3.3.4 Persistence flow

```text
ConfigDB
    ↓
config save
    ↓
/etc/sonic/config_db.json
```

`/run/seriald/config.json` is not used as an input to `config save`.

### 3.3.5 Session display flow

```text
show console-server sessions
        ↓
SONiC show module
        ↓
sonic_console_server_manager
        ↓
independent application session interface
        ↓
validate returned JSON
        ↓
convert nested clients into one row per active client
        ↓
display
```

Session state remains owned by the running independent application and is not stored in ConfigDB or STATE_DB.

### 3.3.6 Product-information flow

```text
SONiC command or manager operation
        ↓
read CONSOLE_SERVER_PRODUCT_INFO|global
        ↓
valid cache?
    ├── yes → use validated cached values
    └── no  → query independent application
               ↓
              validate and normalize live values
               ↓
              best-effort cache update
               ↓
              use validated live values
```

Product information is read-only from the SONiC user perspective.

## 3.4 Responsibility Matrix

| Area | Owning component |
|---|---|
| SONiC CLI parsing and display | SONiC CLI modules |
| Shared SONiC validation and orchestration | `sonic_console_server_manager` |
| Persistent SONiC-owned configuration | ConfigDB |
| Modeled configuration constraints | YANG and CVL |
| Product-information cache validation | `sonic_console_server_manager` |
| Bootstrap and platform-specific settings | `/etc/seriald/config.json` |
| Generated startup configuration | `console-server-config-generate` |
| Service startup and supervision | systemd and `console-server.service` |
| User accounts and passwords | Linux/NSS |
| Serial-console runtime and live sessions | Independent ConsoleServer application |
| Saved SONiC configuration | Standard `config save` mechanism |

## 3.5 Boundary Rules

The following boundary rules shall apply:

1. The independent application shall remain usable without SONiC.
2. SONiC-specific logic shall reside in SONiC CLI modules, the shared manager, ConfigDB/YANG integration, startup generation, service packaging, and image integration.
3. SONiC CLI modules shall not duplicate shared manager logic.
4. The manager shall interact with the independent application through supported external interfaces.
5. Linux/NSS shall remain authoritative for accounts and passwords.
6. ConfigDB shall remain authoritative for persistent SONiC-owned ConsoleServer configuration.
7. `/run/seriald/config.json` shall remain a generated startup output rather than a persistent configuration source.
8. Live session state shall remain owned by the independent application.
9. Product information shall remain read-only to SONiC users and shall be validated by the manager.
10. Standalone application commands shall not be represented as SONiC-owned components.

