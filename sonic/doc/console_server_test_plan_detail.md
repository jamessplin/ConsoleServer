# SONiC ConsoleServer CLI Test Plan

**Target release:** SONiC 202511  
**Scope:** SONiC `config`, `show`, and `connect` commands  
**Status:** Software validation complete; target hardware execution pending

---

# 1. Purpose

This document defines the functional and negative tests for the SONiC ConsoleServer CLI.

The plan verifies:

- command registration and help;
- port, group, and user configuration;
- ConfigDB updates;
- runtime updates;
- display commands;
- interactive connection by line and label;
- standard SONiC persistence;
- validation and error handling;
- rollback and compensation behavior;
- password-protection requirements;
- target-platform command performance.

The plan focuses on SONiC commands. Standalone application CLI commands are outside the normal test interface and are not used as user-facing test steps.

# 2. Scope

## 2.1 In Scope

```text
config console-server port ...
config console-server group ...
config console-server user ...
show console-server port
show console-server group
show console-server user
show console-server sessions
show console-server product-info
connect console-server line ...
connect console-server label ...
config save
```

The tests also verify the related ConfigDB and runtime effects of these commands.

## 2.2 Out of Scope

- Standalone `console-cli` command behavior.
- REST or RESTCONF management.
- STATE_DB session publication.
- Detailed Debian package-build procedures.
- Source migration and porting procedures.
- Full serial-protocol compliance testing.
- A hard Redis transaction for group updates.
- Configurable per-line TCP ports.

# 3. Test Environment

Record:

```text
SONiC image/version:
Platform/HwSKU:
CPU model and core count:
Memory:
Number of physical console lines:
Base TCP port:
Attached serial targets:
Remote client systems:
Tester:
Date:
```

Required access:

- SONiC admin shell;
- root privilege for configuration commands;
- at least one attached serial target;
- ability to open multiple client sessions;
- ability to reboot the DUT;
- access to ConfigDB through `redis-cli -n 4`;
- controlled fault-injection environment for failure tests.

# 4. Entry Criteria

- `console-server.service` is installed.
- `console-server.service` is enabled under `sonic.target`.
- standalone `seriald.service` is disabled in the SONiC image.
- `/usr/local/bin/seriald-status` exists and is executable.
- `/usr/local/bin/console-server-config-generate` exists and is executable.
- `/run/seriald/config.json` is generated when the service starts.
- SONiC ConsoleServer command modules are installed and registered.
- required ConfigDB port rows are present.
- at least one physical console line is operational.

# 5. Automated Regression

## TP-AUTO-001 — Focused unit test suite

```bash
cd <sonic-utilities-source>
pytest -v tests/sonic_console_server_manager/
```

Expected:

- all focused tests pass;
- no unexpected warnings or tracebacks;
- renamed test file `test_console_server_manager.py` is used where applicable.

## TP-AUTO-002 — Syntax and import validation

```bash
python3 -m compileall \
    config/console_server.py \
    show/console_server.py \
    connect/console_server.py \
    sonic_console_server_manager/
```

Expected: no syntax or import errors.

## TP-AUTO-003 — Diff hygiene

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intended files changed.

# 6. CLI Registration and Help

## TP-CLI-001 — Root command registration

```bash
config --help | grep console-server
show --help | grep console-server
connect --help | grep console-server
```

Expected: `console-server` appears under each applicable root command.

## TP-CLI-002 — Nested help

```bash
config console-server --help
config console-server port --help
config console-server group --help
config console-server user --help
show console-server --help
connect console-server --help
```

Expected:

- documented subcommands appear;
- help exits with status `0`;
- unrelated SONiC commands still load correctly.

## TP-CLI-003 — Privilege behavior

Run a configuration command without root privilege.

Expected:

- command is rejected clearly or requests required privilege;
- no runtime or ConfigDB change occurs.

Run show and connect commands as the normal SONiC user.

Expected: commands follow the deployment's documented local access policy.

# 7. Product Information

## TP-PROD-001 — Show product information

```bash
show console-server product-info
```

Expected values match the platform product definition:

```text
Base Port
Max Ports
Max Users
Max Groups
```

## TP-PROD-002 — Valid cache use

```bash
redis-cli -n 4 HGETALL 'CONSOLE_SERVER_PRODUCT_INFO|global'
show console-server product-info
```

Expected:

- complete valid cache fields are accepted;
- displayed values match the cache;
- command does not modify user-configurable tables.

## TP-PROD-003 — Missing cache fallback

```bash
redis-cli -n 4 DEL 'CONSOLE_SERVER_PRODUCT_INFO|global'
show console-server product-info
```

Expected:

- command retrieves valid product information from the authoritative runtime source;
- correct values are displayed;
- manager attempts a best-effort cache update;
- command succeeds even if the cache write is intentionally failed.

## TP-PROD-004 — Incomplete cache repair

```bash
redis-cli -n 4 DEL 'CONSOLE_SERVER_PRODUCT_INFO|global'
redis-cli -n 4 HSET 'CONSOLE_SERVER_PRODUCT_INFO|global' base_port 35000
show console-server product-info
redis-cli -n 4 HGETALL 'CONSOLE_SERVER_PRODUCT_INFO|global'
```

Expected:

- incomplete cache is rejected;
- valid live data is displayed;
- complete normalized cache is written when possible.

## TP-PROD-005 — Invalid cache rejection

```bash
redis-cli -n 4 HSET 'CONSOLE_SERVER_PRODUCT_INFO|global' \
    base_port invalid max_ports 24 max_users 16 max_groups 16
show console-server product-info
```

Expected:

- invalid cache is not used;
- valid fallback is used, or a clear error is shown if no valid source exists;
- no traceback is displayed.

## TP-PROD-006 — TCP overflow validation

Inject product values where:

```text
base_port + max_ports > 65535
```

Expected: values are rejected before use.

# 8. Port Display

## TP-PORT-001 — Show all ports

```bash
show console-server port
```

Expected:

- every initialized line appears;
- lines are sorted numerically;
- all configured fields appear;
- TCP Port is shown as a derived value.

## TP-PORT-002 — TCP-port derivation

Verify several lines using:

```text
tcp_port = base_port + line
```

For base port `35000`:

```text
line 1  → 35001
line 24 → 35024
```

## TP-PORT-003 — ConfigDB comparison

```bash
redis-cli -n 4 HGETALL 'CONSOLE_SERVER_PORT|1'
show console-server port
```

Expected:

- displayed configured fields match ConfigDB;
- TCP port is derived and is not required in the port row.

# 9. Port Configuration

For each test:

1. record the current value;
2. run the SONiC command;
3. verify command status;
4. verify ConfigDB;
5. verify runtime behavior;
6. verify show output;
7. restore the original value.

## TP-PCFG-001 — Baud rate

```bash
sudo config console-server port baudrate 1 9600
```

## TP-PCFG-002 — Data bits

```bash
sudo config console-server port databits 1 8
```

## TP-PCFG-003 — Parity

```bash
sudo config console-server port parity 1 none
```

## TP-PCFG-004 — Stop bits

```bash
sudo config console-server port stopbits 1 1
```

## TP-PCFG-005 — Flow control

```bash
sudo config console-server port flowcontrol 1 none
```

## TP-PCFG-006 — Access mode

```bash
sudo config console-server port mode 1 shared
```

## TP-PCFG-007 — Maximum clients

```bash
sudo config console-server port max-clients 1 4
```

## TP-PCFG-008 — Idle timeout

```bash
sudo config console-server port idle-timeout 1 600
```

## TP-PCFG-009 — Disable idle timeout

```bash
sudo config console-server port idle-timeout 1 0
```

Expected: timeout is disabled.

## TP-PCFG-010 — Label

```bash
sudo config console-server port label 1 DUT-CONSOLE-1
```

Expected for TP-PCFG-001 through TP-PCFG-010:

- exit status `0`;
- runtime updated;
- ConfigDB updated;
- show output displays the new value;
- unrelated fields remain unchanged;
- service restart is not required.

## TP-PCFG-011 — No-op update

Set a field to its current value.

Expected:

- command succeeds;
- no unnecessary runtime update occurs;
- no unnecessary ConfigDB write occurs;
- no rollback path is triggered.

# 10. Port Negative Tests

## TP-PNEG-001 — Port below range

```bash
sudo config console-server port baudrate 0 9600
```

## TP-PNEG-002 — Port above platform limit

```bash
sudo config console-server port baudrate 25 9600
```

Adjust the value for the actual product limit.

## TP-PNEG-003 — Unsupported baud rate

```bash
sudo config console-server port baudrate 1 12345
```

## TP-PNEG-004 — Invalid parity

```bash
sudo config console-server port parity 1 invalid
```

## TP-PNEG-005 — Invalid access mode

```bash
sudo config console-server port mode 1 invalid
```

## TP-PNEG-006 — Idle timeout above maximum

```bash
sudo config console-server port idle-timeout 1 86401
```

## TP-PNEG-007 — Duplicate label

Assign line 2 the label already owned by line 1.

## TP-PNEG-008 — Reserved label conflict

Attempt to assign a reserved default label such as `COM2` to the wrong line.

Expected for all negative tests:

- nonzero exit status;
- clear error message;
- no runtime change;
- no ConfigDB change;
- no traceback.

# 11. Group Configuration

## TP-GRP-001 — Add group with range

```bash
sudo config console-server group add lab 1-5,8 --role console_user
```

Expected:

- parent group row exists;
- normalized membership rows exist;
- runtime group is created;
- `show console-server group` displays sorted ports.

## TP-GRP-002 — Replace group role and membership

```bash
sudo config console-server group add lab 2,4,6 --role operator
```

Expected:

- role is replaced;
- complete membership is replaced;
- stale memberships are removed;
- omitted old members are not preserved.

## TP-GRP-003 — Use `all`

```bash
sudo config console-server group add allports all
```

Expected: every initialized console line is included.

## TP-GRP-004 — Delete group

```bash
sudo config console-server group delete lab
```

Expected:

- runtime group is removed;
- parent row is removed;
- membership rows are removed;
- unrelated groups remain unchanged.

## TP-GRP-005 — No-op group replacement

Reapply the same role and membership.

Expected: success without unnecessary changes.

# 12. Group Negative Tests

## TP-GNEG-001 — Unknown port

```bash
sudo config console-server group add badgroup 999
```

## TP-GNEG-002 — Malformed range

```bash
sudo config console-server group add badgroup 1-3,,5
```

## TP-GNEG-003 — Unsupported role

```bash
sudo config console-server group add badgroup 1 --role observer
```

## TP-GNEG-004 — Empty membership

Attempt to create or replace a group without a valid port list.

## TP-GNEG-005 — Delete nonexistent group

Delete a group that does not exist.

Expected:

- deterministic command behavior;
- no unrelated runtime or ConfigDB changes;
- clear error where the operation is rejected.

# 13. User Configuration

Use dedicated temporary Linux/NSS users.

## TP-USR-001 — Add user with prompted password

```bash
sudo config console-server user add cs_test1 \
    --role operator \
    --groups allports \
    --prompt-password
```

Expected:

- password prompt is hidden and confirmed;
- Linux/NSS user exists;
- ConfigDB role and group metadata exist;
- password is not present in ConfigDB;
- password is not displayed by show commands.

## TP-USR-002 — Metadata-only role update

```bash
sudo config console-server user add cs_test1 --role admin
```

Expected:

- role changes;
- existing groups are preserved;
- existing password remains valid.

## TP-USR-003 — Groups-only update

```bash
sudo config console-server user add cs_test1 --groups group2
```

Expected:

- group membership is replaced with the requested complete set;
- existing role is preserved;
- password remains unchanged.

## TP-USR-004 — Password-only update

```bash
sudo config console-server user password cs_test1 --prompt-password
```

Expected:

- Linux/NSS password changes;
- ConfigDB role and groups remain unchanged.

## TP-USR-005 — Show user metadata

```bash
show console-server user
```

Expected:

- username, role, and groups appear;
- password or password hash does not appear.

## TP-USR-006 — Delete user

```bash
sudo config console-server user delete cs_test1
```

Expected:

- Linux/NSS user is removed according to command behavior;
- ConfigDB metadata is removed;
- unrelated users remain unchanged.

# 14. User Negative and Security Tests

## TP-UNEG-001 — Conflicting password options

Use `--password` and `--prompt-password` together.

Expected: rejected before any state change.

## TP-UNEG-002 — Unknown group

Attempt to assign a nonexistent group.

Expected: rejected before Linux/NSS or ConfigDB mutation.

## TP-UNEG-003 — Password command without password input mode

Expected: rejected with a clear message.

## TP-UNEG-004 — Invalid role

Attempt to set an unsupported ConsoleServer role.

Expected: rejected before state change.

## TP-USEC-001 — Password absence from output and logs

Verify the test password does not appear in:

```text
show console-server user
journalctl
syslog
CLI error output
unit-test output
exception text
/run/seriald/config.json
ConfigDB
```

## TP-USEC-002 — Shell-injection resistance

Use controlled usernames, labels, or group names containing shell metacharacters where input rules allow them.

Expected:

- values are rejected or passed literally;
- no shell command is executed;
- external commands use `shell=False` behavior.

Document the accepted transient process-argument exposure if the password is passed to a child process.

# 15. Interactive Connection

## TP-CONN-001 — Connect by line

```bash
connect console-server line 1
```

Expected:

- interactive terminal opens;
- input reaches the attached target;
- output is visible;
- configured escape sequence disconnects cleanly;
- child exit status is propagated.

## TP-CONN-002 — Connect by label

```bash
connect console-server label DUT-CONSOLE-1
```

Expected: connection reaches the same physical line as TP-CONN-001.

## TP-CONN-003 — Shared mode clients

Open clients up to `max_clients`.

Expected:

- allowed clients connect;
- `show console-server sessions` displays each active client.

## TP-CONN-004 — Exceed maximum clients

Attempt one additional connection.

Expected: connection is rejected clearly.

## TP-CONN-005 — Exclusive mode

Set the line to exclusive mode and attempt a second connection.

Expected: second connection is rejected.

## TP-CNEG-001 — Unknown line

```bash
connect console-server line 999
```

Expected: rejected before launching the connection process.

## TP-CNEG-002 — Unknown label

Expected: clear error and no connection attempt.

## TP-CNEG-003 — Label case sensitivity

Use the correct label with different letter case.

Expected: no match because lookup is exact and case-sensitive.

# 16. Session Display

## TP-SES-001 — No active sessions

Disconnect all clients and run:

```bash
show console-server sessions
```

Expected:

```text
No active console-server sessions.
```

## TP-SES-002 — One active session

Connect one client and run the show command.

Expected: one row with correct line, mode, user, role, client address, idle timeout, and time left.

## TP-SES-003 — Multiple clients on one line

Expected: one row per active client.

## TP-SES-004 — Multiple active lines

Expected: deterministic numeric line ordering.

## TP-SES-005 — Internal fields omitted

Expected: internal fields such as `session_id` and `last_activity` are not displayed.

## TP-SES-006 — Time-left behavior

Wait without activity and rerun the command.

Expected:

- Time Left decreases;
- client activity resets it according to runtime behavior.

## TP-SES-007 — Malformed runtime response

Inject malformed or structurally invalid runtime session data.

Expected:

- clear non-sensitive error;
- nonzero exit status;
- no traceback to the user.

## TP-SES-008 — Runtime unavailable

Stop or isolate the runtime in a controlled environment.

Expected: clear failure without modifying ConfigDB.

# 17. Persistence and Restart

## TP-PERS-001 — Save configuration

Apply representative port, group, and user-metadata changes:

```bash
sudo config save -y
```

Expected: saved SONiC configuration contains the modeled ConsoleServer tables.

## TP-PERS-002 — Reboot persistence

Reboot the DUT.

Expected:

- saved port values are restored;
- saved groups and memberships are restored;
- saved user role/group metadata is restored;
- Linux/NSS passwords remain valid;
- runtime configuration is regenerated;
- show commands succeed.

## TP-PERS-003 — Service restart

```bash
sudo systemctl restart console-server.service
```

Expected:

- generator runs before the runtime starts;
- `/run/seriald/config.json` is regenerated;
- service reaches active state;
- saved ConfigDB configuration is applied.

## TP-PERS-004 — Runtime snapshot behavior

Apply a normal live port change without restarting the service.

Expected:

- runtime and ConfigDB reflect the new value;
- `/run/seriald/config.json` may still contain the startup value;
- after service restart, the file is regenerated from persistent inputs.

## TP-PERS-005 — Generator failure

Inject invalid startup input and restart the service.

Expected:

- invalid candidate file does not replace the previous valid file;
- `server.py` is not started;
- service reports a clear failure.

# 18. Consistency and Failure Injection

## TP-FAIL-001 — Port runtime update succeeds, ConfigDB write fails

Inject a ConfigDB write failure after runtime update.

Expected:

- runtime rollback is attempted;
- user receives a clear error;
- final runtime and ConfigDB states are inspected and recorded.

## TP-FAIL-002 — Group ConfigDB update fails midway

Inject failure after one or more group rows have been written.

Expected:

- runtime compensation is attempted;
- partial ConfigDB metadata is detected;
- reapplying the intended group configuration restores consistency;
- no claim of atomic rollback is made.

## TP-FAIL-003 — Linux/NSS user operation succeeds, ConfigDB fails

Inject a ConfigDB failure after the account operation.

Expected:

- command reports the inconsistency;
- Linux/NSS state and ConfigDB metadata are inspected;
- documented manual recovery is usable.

## TP-FAIL-004 — Product cache write fails

Force a cache-write failure during product-info fallback.

Expected:

- validated product information is still displayed;
- subsequent calls retry while the cache remains missing or invalid.

# 19. Performance

Run one cold iteration and five warm iterations on development and target hardware.

```bash
for i in 1 2 3 4 5; do
    /usr/bin/time -f 'real=%e user=%U sys=%S cpu=%P' \
        show console-server port >/dev/null
done

for i in 1 2 3 4 5; do
    /usr/bin/time -f 'real=%e user=%U sys=%S cpu=%P' \
        show console-server sessions >/dev/null
done

for i in 1 2 3 4 5; do
    /usr/bin/time -f 'real=%e user=%U sys=%S cpu=%P' \
        show console-server product-info >/dev/null
done
```

Record:

- cold time;
- warm minimum;
- warm median;
- warm maximum;
- CPU utilization;
- system load;
- number of active sessions.

Performance remains informational until targets are agreed for the final platform, unless command latency causes timeout or usability failure.

# 20. Long-Duration and Concurrency Tests

## TP-STRESS-001 — Repeated show commands

Run each show command at least 1,000 times.

Expected:

- no crash;
- no memory leak indication;
- no unintended ConfigDB mutation except valid product-info caching;
- stable output formatting.

## TP-STRESS-002 — Concurrent session display

Run multiple `show console-server sessions` commands concurrently.

Expected: correct output and no runtime instability.

## TP-STRESS-003 — Concurrent group updates

In a controlled environment, issue competing updates to the same group.

Expected:

- final state is valid and documented;
- any partial-write behavior is detectable;
- no unrelated group is changed.

## TP-STRESS-004 — Session churn

Repeatedly connect and disconnect clients while polling sessions.

Expected:

- no stale rows after disconnect;
- no command exceptions;
- no ConfigDB session entries are created.

# 21. Exit Criteria

- Focused automated tests pass.
- All CLI registration and help tests pass.
- All critical port, group, user, show, and connect cases pass.
- Negative tests leave runtime and ConfigDB unchanged.
- No password appears in ConfigDB, runtime configuration, output, logs, or exceptions.
- Port rollback behavior is verified.
- Group partial-update and compensation behavior is verified.
- User cross-system failure recovery is verified.
- Standard `config save`, reboot, and service restart behavior are verified.
- Runtime snapshot behavior is understood and documented.
- Target-hardware performance is measured and reviewed.
- Remaining limitations are recorded in `known_issues.md`.
