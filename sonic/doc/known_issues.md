# Console Server Integration — Known Issues

This document records open issues, limitations, deployment requirements, and resolved defects for the SONiC console-server integration.

**Updated:** 2026-07-08

## Open Issues

### 1. Password can be exposed through process arguments

**Status:** Open / documented security limitation

The independent application accepts passwords through:

```bash
console-cli config user add <username> --password <password>
```

The SONiC CLI offers hidden interactive input through `--prompt-password`, but the manager must still pass the resulting password to the child process in `argv`.

A privileged user may briefly inspect it through:

```bash
ps auxww | grep console-cli
pgrep -af console-cli
cat /proc/<pid>/cmdline | tr '\0' ' '
```

Required safeguards:

- use `shell=False`;
- never log complete command arguments;
- never include passwords in exceptions;
- mask passwords in debug output;
- keep the child process lifetime short.

A future stdin, file-descriptor, or Unix-socket password interface is needed to eliminate this exposure.

---

### 2. User operations are not atomic across application/Linux state and ConfigDB

**Status:** Open / documented consistency limitation

User management changes two systems:

1. console-server application and Linux account state;
2. ConfigDB user metadata.

Current flow:

```text
validate metadata
→ console-cli user operation
→ direct ConfigDB update
```

Failure window:

```text
console-cli succeeds
but ConfigDB update fails
```

Automatic rollback is not always safe because the previous password and complete Linux account state are unavailable.

Recovery remains manual:

```text
inspect console-cli/application users
inspect Linux account state
inspect CONSOLE_SERVER_USER
inspect CONSOLE_SERVER_USER_GROUP
reapply or remove metadata as appropriate
```

---

### 3. Group ConfigDB changes are sequential rather than a hard Redis transaction

**Status:** Future robustness improvement / not a release blocker

A group update may modify:

```text
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
```

The manager validates the complete candidate and sends one runtime update, but ConfigDB rows are written sequentially. A low-level failure during the batch could leave partial metadata.

Runtime compensation is attempted when ConfigDB fails, but previously written ConfigDB rows are not automatically rolled back as one Redis transaction.

---

### 4. Console-port inventory requires boot-time initialization

**Status:** Open / next implementation task

`CONSOLE_SERVER_PORT` is the authoritative physical console-port inventory for validation and show commands.

If it is empty, group and connection validation cannot reliably determine valid ports.

The boot path must create one complete row for every physical line:

```text
CONSOLE_SERVER_PORT|1
CONSOLE_SERVER_PORT|2
...
CONSOLE_SERVER_PORT|<max_ports>
```

Each row should contain complete defaults, including a unique label such as `COM1`.

The initializer must be idempotent and must define whether existing user-modified entries are preserved, merged, repaired, or overwritten.

---

### 5. Startup ownership and synchronization are not finalized

**Status:** Open / initialization design issue

ConfigDB and the console-server runtime may start with different values.

Examples observed during development:

```text
ConfigDB label       = COM1
Runtime label        = xxxT

ConfigDB max_clients = 1
Runtime max_clients  = 4
```

The boot design must establish:

- which source is authoritative;
- whether ConfigDB is pushed to runtime or runtime is imported into ConfigDB;
- how saved user configuration is preserved;
- how missing or invalid rows are repaired;
- what happens when synchronization partially fails.

---

### 6. Product info is lazily cached rather than explicitly initialized at boot

**Status:** Functional interim solution / boot initialization pending

Current behavior:

```text
read CONSOLE_SERVER_PRODUCT_INFO|global
→ if valid, use it
→ otherwise call console-cli show product-info --json
→ best-effort cache the normalized values
```

A failed cache write does not fail the show command.

This works immediately and accelerates later commands, but product-info population should be moved into the boot-time initialization flow so ordinary show commands are consistently read-only in normal operation.

The boot initializer should populate:

```text
CONSOLE_SERVER_PRODUCT_INFO|global
    base_port
    max_ports
    max_users
    max_groups
```

---

### 7. Product-info cache has no explicit version or freshness marker

**Status:** Open / upgrade consideration

Once cached, product info is trusted when complete and valid. If firmware, application configuration, or platform limits change after an upgrade, an old valid cache entry may remain.

The boot initializer should refresh or validate product info against the platform/application source. A schema or source-version field may be added if upgrade policy requires it.

---

### 8. CLI startup is slow on the two-core ARM development platform

**Status:** Deferred pending target-hardware measurement

Measured values:

| Command | Real time |
|---|---:|
| `console-cli show sessions --json` | 2.455 s |
| `show console-server port` | 5.041 s |
| `show console-server sessions` | 6.095 s |

The measured command was predominantly CPU-bound. The main costs are Python startup, SONiC Click command-tree imports, and launching the independent `console-cli` process.

The four-core target may improve behavior under load, but doubling core count will not halve latency because most startup work is sequential.

Re-measure on the final target before optimizing. Possible later improvements:

- lazy imports and lazy command registration;
- smaller dedicated runtime-status executable;
- persistent local API/service.

---

### 9. Session display depends on the independent application's live CLI

**Status:** Accepted current design

`show console-server sessions` calls:

```bash
console-cli show sessions --json
```

If `console-cli` or `seriald` is unavailable or slow, the SONiC command fails or is delayed.

Session state is intentionally not mirrored into STATE_DB in the first implementation, avoiding duplicated and potentially stale runtime state.

---

### 10. Product-info fallback can cause a show command to write ConfigDB

**Status:** Accepted interim behavior

When the product-info cache is absent or invalid, the show path retrieves live product information and attempts to populate ConfigDB.

The cache write is best effort, so display still succeeds if the write fails. Nevertheless, this means the first show command can have a write side effect.

Boot-time initialization will remove this side effect during normal operation.

---

### 11. TCP port is derived and assumes a fixed sequential mapping

**Status:** Accepted platform assumption

The SONiC display calculates:

```text
tcp_port = base_port + line
```

This is correct only while the independent application guarantees a sequential mapping. If per-line TCP ports become configurable, the schema and manager must expose the actual mapping rather than derive it.

---

## Resolved Issues

### A. Slow port updates caused by GCU dry-run and commit

Port updates now use local validation, `seriald-status`, direct ConfigDB commit, and runtime rollback on ConfigDB failure.

### B. Slow and split group update flow

Group configuration now uses one combined manager API and one runtime command.

### C. Compound ConfigDB keys returned as tuples

The manager accepts tuple and pipe-delimited forms for compound keys.

### D. Group roles and defaults differed from the YANG model

Valid group roles are `admin`, `console_user`, and `operator`; default is `console_user`.

### E. Empty group port lists were accepted

The port list is now required for group add/update.

### F. SONiC manager duplicated Linux account management

Linux-user operations are delegated to the independent `console-cli` interface.

### G. User-delete backend used the wrong verb

The manager now calls `console-cli config user delete`.

### H. ConfigDB-backed show commands were missing

Port, group, and user show commands are implemented and verified.

### I. Group-only user update reset the existing role

Omitted role now preserves an existing user's role.

### J. Interactive enhanced connect commands were missing

Implemented:

```bash
connect console-server line <port_number>
connect console-server label <label>
```

The interactive child process inherits stdin, stdout, and stderr.

### K. Runtime session display was missing

Implemented `show console-server sessions` using validated JSON from the independent application.

### L. Product information and TCP-port visibility were missing

Implemented `show console-server product-info`, ConfigDB read-through caching, and derived TCP-port display in `show console-server port`.

## To-Do Summary

- Implement boot-time initialization of `CONSOLE_SERVER_PORT`.
- Populate or refresh `CONSOLE_SERVER_PRODUCT_INFO` during boot.
- Define startup ownership and synchronization policy.
- Define upgrade behavior for existing and incomplete ConfigDB rows.
- Re-measure CLI performance on the four-core target.
- Consider a Redis transaction only if stronger group-write atomicity is required.
- Consider secure non-argv password transport.
- Maintain documented recovery procedures for user-state inconsistency.
