# Console Server Integration — Known Issues

This document records issues and limitations discovered while integrating the independent console-server application with SONiC.

## Open Issues

### 1. Password handling and non-interactive automation

**Status:** Open / deferred follow-up

The current SONiC CLI prompts for the password securely and does not echo it:

```bash
config console-server user add <username> --password
config console-server user password <username>
```

This is appropriate for interactive use.

However, the independent application currently accepts the password only as a command argument:

```bash
console-cli config user add <username> --password <password>
```

Therefore, after the SONiC CLI collects the password securely, the manager must pass it to `console-cli` through `argv`.

While `console-cli` is running, a privileged user may briefly see the password through commands such as:

```bash
ps auxww | grep console-cli
pgrep -af console-cli
cat /proc/<pid>/cmdline | tr '\0' ' '
```

The SONiC integration must:

- never use `shell=True`;
- never log the complete command arguments;
- never include the password in exception messages;
- mask the password in debug output;
- keep the application command execution as short as possible.

A future non-interactive mode is also required for batch and automation use. The preferred design is:

```text
--password-stdin
```

with the password passed from the SONiC CLI to `console-cli` through standard input instead of process arguments.

Possible later additions:

```text
--password-file
batch user import with protected secret-file references
```

Plaintext passwords in normal positional or option arguments should not be exposed as a public SONiC CLI interface.

Implementation of the non-interactive mode is intentionally deferred until after the current code is committed.

---

### 2. User operations are not atomic across the application and ConfigDB

**Status:** Open / documented limitation

User management affects two independent systems:

1. the console-server application and Linux account state;
2. SONiC ConfigDB metadata.

There is no distributed transaction covering both systems.

#### Create or update user

Current flow:

```text
Validate console-server metadata locally
→ console-cli config user add
→ direct ConfigDB commit
```

Failure window:

```text
console-cli succeeds
but ConfigDB commit fails
```

Possible result:

```text
Application/Linux user is created or updated
ConfigDB metadata remains old or absent
```

Automatic rollback is unsafe because:

- a changed password cannot be restored without the previous password;
- the account may have existed before the operation;
- deleting the account as compensation could destroy valid state.

#### Delete user

Current flow:

```text
Validate console-server metadata locally
→ console-cli config user delete
→ direct ConfigDB deletion
```

Failure window:

```text
console-cli deletion succeeds
but ConfigDB commit fails
```

Possible result:

```text
Application/Linux user is deleted
stale ConfigDB metadata remains
```

Recreating the original user automatically is not reliable because the previous password and other Linux account state are unavailable.

#### Recovery

Recovery is manual:

```text
Inspect console-cli/runtime user state
Inspect Linux account state
Inspect CONSOLE_SERVER_USER
Inspect CONSOLE_SERVER_USER_GROUP
Reapply or remove the user configuration as appropriate
```

---

### 3. User commands previously depended on full GCU/CVL validation

**Status:** Resolved

The earlier user path was:

```text
GCU/CVL dry-run
→ console-cli
→ GCU commit
```

Because GCU validated the complete ConfigDB, an unrelated invalid table could block a console-server user operation.

Observed example:

```text
CONSOLE_PORT rows contained local_device
but the installed sonic-console.yang did not define that leaf
→ full ConfigDB validation rejected console-server user creation
```

The user path was changed to:

```text
local console-server validation
→ console-cli
→ direct ConfigDB commit
```

Results:

- unrelated ConfigDB tables no longer block console-server user commands;
- the `Patch Applier` output is gone;
- the cross-system consistency limitation remains documented in Issue 2.


---

### 4. Group direct ConfigDB updates are not a hard Redis transaction

**Status:** Open

Group add/update/delete uses the fast path:

```text
manager validation
→ one console-server runtime command
→ direct ConfigDB writes
```

This reduced execution time from approximately 52–71 seconds to about 3 seconds.

However, `commit_direct()` currently writes multiple ConfigDB rows sequentially. A low-level failure in the middle of the batch could leave partial ConfigDB state.

Examples of multi-row operations:

```text
CONSOLE_SERVER_GROUP
CONSOLE_SERVER_GROUP_PORT
CONSOLE_SERVER_USER_GROUP
```

A future improvement should use a true atomic Redis transaction or an equivalent ConfigDB batch mechanism.

---

### 5. Console-port inventory must be populated before group validation

**Status:** Open / deployment requirement

The manager treats keys in `CONSOLE_SERVER_PORT` as the authoritative physical console-port inventory.

If the table is empty:

```text
Error: CONSOLE_SERVER_PORT is empty or unavailable
```

The platform boot or initialization path must create one complete row for every physical console port.

Example required keys:

```text
CONSOLE_SERVER_PORT|1
CONSOLE_SERVER_PORT|2
...
```

Each row should include the complete default configuration, including a unique label such as `COM1`.

The production initialization mechanism is still to be finalized.

---

### 6. Runtime and ConfigDB can start with different values

**Status:** Open / initialization issue

During development, existing discrepancies were observed between ConfigDB and the console-server runtime, for example:

```text
ConfigDB label       = COM1
Runtime label        = xxxT

ConfigDB max_clients = 1
Runtime max_clients  = 4
```

Interactive commands update both layers, but startup synchronization and ownership still need to be clearly defined.

The boot flow must establish which component is authoritative and synchronize the other layer.

---

### 7. User CLI operations have noticeable startup and application overhead

**Status:** Known limitation / measured on development switch

Measured results:

| Command | Real time |
|---|---:|
| `console-cli config user add testuser2 ...` | 3.784 s |
| `console-cli config user delete testuser2` | 3.527 s |
| `config console-server user add testuser3 ...` | 16.436 s, including interactive password-entry time |
| `config console-server user delete testuser3` | 4.928 s |
| `config console-server user --help` | 2.641 s |
| `config console-server --help` | 3.256 s |

Observations:

- the SONiC `config` command has a baseline startup cost of approximately 2.6–3.3 seconds;
- direct `console-cli` user add/delete takes approximately 3.5–3.8 seconds;
- normal SONiC user deletion is broadly consistent with framework startup plus application work;
- the 16.436-second SONiC user-add measurement includes the time spent entering and confirming the password, so it is not a pure command-performance measurement;
- the earlier first delete measurement of 11.949 seconds indicates cold-start or one-time initialization effects may exist;
- subsequent deletion completed in 4.928 seconds.

A new automated measurement is required before concluding that the SONiC user-add implementation itself is unusually slow. The next measurement should exclude human input time, preferably after a secure `--password-stdin` mode or targeted internal timing instrumentation is available.

`strace` was not available on the development switch:

```text
sudo: strace: command not found
```

Further profiling requires installing a tracing tool in a development image or adding timestamped instrumentation around:

```text
SONiC CLI startup
manager validation
console-cli subprocess execution
direct ConfigDB commit
```


---

## Resolved Issues

### A. Slow port updates caused by GCU dry-run and commit

**Status:** Resolved

Port commands were changed from:

```text
GCU dry-run
→ seriald-status
→ GCU commit
```

to:

```text
manager validation
→ seriald-status
→ direct ConfigDB commit
→ runtime rollback if the DB write fails
```

No-op detection and changed-field-only updates were also added.

---

### B. Slow and non-combined group CLI flow

**Status:** Resolved

Previously, group creation used two separate manager calls:

```text
create/update group
set group ports
```

The flow now uses one combined API:

```text
set_group_config(group_name, role, ports)
```

This validates the complete candidate before changing runtime and sends one combined runtime command.

---

### C. Compound ConfigDB keys returned as tuples

**Status:** Resolved

`ConfigDBConnector.get_table()` may return compound keys as tuples:

```python
("ops", "1")
```

The manager previously assumed pipe-delimited strings:

```python
"ops|1"
```

This caused group deletion to fail with:

```text
AttributeError: 'tuple' object has no attribute 'startswith'
```

The manager now accepts both tuple and pipe-delimited forms for:

```text
CONSOLE_SERVER_GROUP_PORT
CONSOLE_SERVER_USER_GROUP
```

---

### D. Group roles and defaults did not match the YANG model

**Status:** Resolved

Group roles are now limited to:

```text
admin
console_user
operator
```

The default group role is:

```text
console_user
```

Unsupported values such as `observer` and `none` are rejected.

---

### E. Group port list was optional

**Status:** Resolved

The group port list is now a required positional argument:

```bash
config console-server group add <group_name> <port_list> [--role <role>]
```

This prevents creation of operationally empty groups through the SONiC CLI.

---

### F. SONiC manager duplicated Linux account handling

**Status:** Resolved

Direct Linux/NSS account management was removed from the SONiC integration:

```text
pwd.getpwnam
useradd
userdel
chpasswd
NssUserBackend
```

SONiC now uses only the independent application's public CLI:

```text
console-cli config user add
console-cli config user delete
```

The independent console-server application remains SONiC-agnostic and owns Linux-user handling.

---

### G. User-delete backend command did not match the application CLI

**Status:** Resolved

The manager originally called:

```text
console-cli config user del <username>
```

The application supports:

```text
console-cli config user delete <username>
```

The manager and regression test were updated to use `delete`.

---


## To-Do Summary

- Implement a true atomic Redis transaction for multi-row group changes.
- Implement secure non-interactive password input, preferably `--password-stdin`, in both `console-cli` and the SONiC wrapper.
- Finalize boot-time population of `CONSOLE_SERVER_PORT`.
- Define startup synchronization between ConfigDB and console-server runtime.
- Re-measure SONiC user-add performance without including human password-entry time.
- Add operational recovery instructions for inconsistent user state.
