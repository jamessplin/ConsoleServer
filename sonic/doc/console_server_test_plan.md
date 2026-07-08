# SONiC Console-Server Test Plan

**Version:** 1.0  
**Date:** 2026-07-08

## 1. Purpose

Verify the SONiC console-server CLI, ConfigDB schema usage, independent application integration, runtime behavior, persistence, validation, error handling, security properties, and performance on the target platform.

## 2. Scope

In scope:

- Port configuration.
- Group configuration.
- User configuration.
- Show commands.
- Interactive connect by line and label.
- Product-info ConfigDB cache.
- TCP-port derivation.
- Runtime and ConfigDB consistency.
- Save/reboot persistence.
- Negative and recovery tests.
- CLI startup performance.

Out of scope unless implemented later:

- REST API.
- STATE_DB session publication.
- True Redis `MULTI/EXEC` group transaction.
- Per-line configurable TCP ports.

## 3. Test environment

Record:

```text
SONiC image/version:
Platform/HwSKU:
CPU model and core count:
Memory:
Console-server application version:
seriald version/status:
Number of physical console lines:
Base TCP port:
Tester/date:
```

Required access:

- SONiC admin/root shell.
- At least one attached serial target.
- One or more remote TCP clients.
- Ability to reboot the DUT.
- Access to ConfigDB through `redis-cli -n 4`.

## 4. Entry criteria

- `seriald` is running.
- `/usr/local/bin/seriald-status` exists and is executable.
- `/usr/local/bin/console-cli` exists and is executable.
- SONiC command modules are installed and registered.
- YANG/CVL package is installed when required by the image.
- `CONSOLE_SERVER_PORT` is initialized, or the initialization test is intentionally being executed.

## 5. Automated regression

### TP-AUTO-001 — Complete console-server unit suite

```bash
cd <sonic-utilities-source>
pytest -v tests/sonic_console_server_manager/
```

Expected: all tests pass.

### TP-AUTO-002 — Syntax and import check

```bash
python3 -m compileall \
    config/console_server.py \
    show/console_server.py \
    connect/console_server.py \
    sonic_console_server_manager/
```

Expected: no syntax or import compilation errors.

### TP-AUTO-003 — Diff hygiene

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files changed.

## 6. CLI registration and help

### TP-CLI-001 — Root command registration

```bash
config --help | grep console-server
show --help | grep console-server
connect --help | grep console-server
```

Expected: `console-server` appears under all applicable root commands.

### TP-CLI-002 — Nested help

```bash
config console-server --help
config console-server port --help
config console-server group --help
config console-server user --help
show console-server --help
connect console-server --help
```

Expected: documented subcommands appear and help exits with status 0.

## 7. Product information and cache

### TP-PROD-001 — Live product-info fallback

```bash
redis-cli -n 4 DEL "CONSOLE_SERVER_PRODUCT_INFO|global"
show console-server product-info
```

Expected: correct product values are displayed.

### TP-PROD-002 — Cache population

```bash
redis-cli -n 4 HGETALL "CONSOLE_SERVER_PRODUCT_INFO|global"
```

Expected fields:

```text
base_port
max_ports
max_users
max_groups
```

### TP-PROD-003 — Cache hit without console-cli

After populating the cache, temporarily make `console-cli` unavailable in a controlled environment and run:

```bash
show console-server product-info
show console-server port
```

Expected: both succeed using ConfigDB. Restore the binary immediately.

### TP-PROD-004 — Incomplete cache repair

```bash
redis-cli -n 4 DEL "CONSOLE_SERVER_PRODUCT_INFO|global"
redis-cli -n 4 HSET "CONSOLE_SERVER_PRODUCT_INFO|global" base_port 35000
show console-server product-info
redis-cli -n 4 HGETALL "CONSOLE_SERVER_PRODUCT_INFO|global"
```

Expected: incomplete entry is ignored and replaced with complete valid data.

### TP-PROD-005 — Invalid cache repair

Set a non-integer value:

```bash
redis-cli -n 4 HSET "CONSOLE_SERVER_PRODUCT_INFO|global" \
    base_port invalid max_ports 24 max_users 16 max_groups 16
show console-server product-info
```

Expected: command falls back to live data and repairs the cache.

### TP-PROD-006 — TCP overflow validation

Inject values where `base_port + max_ports > 65535`.

Expected: invalid cache is rejected; valid fallback is used, or a clear error is shown if the live source is also invalid.

## 8. Port display and TCP mapping

### TP-PORT-001 — Show all ports

```bash
show console-server port
```

Expected:

- all initialized lines appear;
- numeric line order;
- TCP Port column appears;
- all configured fields appear.

### TP-PORT-002 — TCP-port calculation

For several lines, verify:

```text
tcp_port = base_port + line
```

Example with base port 35000:

```text
line 1  → 35001
line 24 → 35024
```

### TP-PORT-003 — Raw ConfigDB comparison

```bash
redis-cli -n 4 HGETALL "CONSOLE_SERVER_PORT|1"
show console-server port
```

Expected: displayed configuration matches ConfigDB; TCP port is the only derived value.

## 9. Port configuration

For every field, record pre-state, execute the command, verify ConfigDB, verify runtime, and restore the original value.

### TP-PCFG-001 — Baud rate

```bash
sudo config console-server port baudrate 1 9600
```

### TP-PCFG-002 — Data bits

```bash
sudo config console-server port databits 1 8
```

### TP-PCFG-003 — Parity

```bash
sudo config console-server port parity 1 none
```

### TP-PCFG-004 — Stop bits

```bash
sudo config console-server port stopbits 1 1
```

### TP-PCFG-005 — Flow control

```bash
sudo config console-server port flowcontrol 1 none
```

### TP-PCFG-006 — Access mode

```bash
sudo config console-server port mode 1 shared
```

### TP-PCFG-007 — Maximum clients

```bash
sudo config console-server port max-clients 1 4
```

### TP-PCFG-008 — Idle timeout

```bash
sudo config console-server port idle-timeout 1 600
```

### TP-PCFG-009 — Disable idle timeout

```bash
sudo config console-server port idle-timeout 1 0
```

Expected: timeout is disabled.

### TP-PCFG-010 — Label

```bash
sudo config console-server port label 1 DUT-CONSOLE-1
```

Expected for TP-PCFG-001 through TP-PCFG-010:

- exit status 0;
- ConfigDB updated;
- runtime updated;
- `show console-server port` displays the new value;
- unrelated fields unchanged.

### TP-PCFG-011 — No-op update

Set a field to its current value.

Expected: success without unnecessary state changes; no inconsistency.

## 10. Port negative tests

### TP-PNEG-001 — Port below range

```bash
sudo config console-server port baudrate 0 9600
```

Expected: rejected; no runtime or ConfigDB change.

### TP-PNEG-002 — Port above platform maximum

```bash
sudo config console-server port baudrate 25 9600
```

Adjust for the actual platform maximum.

### TP-PNEG-003 — Unsupported baud rate

```bash
sudo config console-server port baudrate 1 12345
```

### TP-PNEG-004 — Invalid parity

```bash
sudo config console-server port parity 1 invalid
```

### TP-PNEG-005 — Invalid mode

```bash
sudo config console-server port mode 1 invalid
```

### TP-PNEG-006 — Idle timeout above maximum

```bash
sudo config console-server port idle-timeout 1 86401
```

### TP-PNEG-007 — Duplicate label

Assign line 2 the label already owned by line 1.

Expected for negative tests: nonzero exit, clear error, no partial runtime or ConfigDB change.

## 11. Group configuration

### TP-GRP-001 — Add group with range

```bash
sudo config console-server group add lab 1-5,8 --role console_user
```

Expected:

- parent group row exists;
- normalized member rows exist;
- `show console-server group` displays sorted ports.

### TP-GRP-002 — Replace group membership

```bash
sudo config console-server group add lab 2,4,6 --role operator
```

Expected: role and complete membership are replaced; stale memberships removed.

### TP-GRP-003 — Use `all`

```bash
sudo config console-server group add allports all
```

Expected: every initialized console line is included.

### TP-GRP-004 — Delete group

```bash
sudo config console-server group delete lab
```

Expected: parent and member rows removed; runtime group removed.

### TP-GNEG-001 — Unknown port

```bash
sudo config console-server group add badgroup 999
```

Expected: rejected.

### TP-GNEG-002 — Malformed range

```bash
sudo config console-server group add badgroup 1-3,,5
```

### TP-GNEG-003 — Unsupported role

```bash
sudo config console-server group add badgroup 1 --role observer
```

### TP-GNEG-004 — Delete nonexistent group

Expected: clear deterministic behavior and no unrelated changes.

## 12. User configuration

Use dedicated temporary test users.

### TP-USR-001 — Add user with prompted password

```bash
sudo config console-server user add cs_test1 \
    --role operator \
    --groups allports \
    --prompt-password
```

Expected:

- hidden prompt with confirmation;
- Linux/application user exists;
- ConfigDB metadata exists;
- password not displayed by show commands.

### TP-USR-002 — Metadata-only role update

```bash
sudo config console-server user add cs_test1 --role admin
```

Expected: groups and password preserved.

### TP-USR-003 — Groups-only update

```bash
sudo config console-server user add cs_test1 --groups group2
```

Expected: existing role preserved.

### TP-USR-004 — Password-only update

```bash
sudo config console-server user password cs_test1 --prompt-password
```

Expected: metadata unchanged.

### TP-USR-005 — Delete user

```bash
sudo config console-server user delete cs_test1
```

Expected: application/Linux user and ConfigDB metadata removed.

### TP-UNEG-001 — Both password modes

Use `--password` and `--prompt-password` together.

Expected: rejected before changing state.

### TP-UNEG-002 — Unknown group

Expected: rejected before user/application mutation.

### TP-UNEG-003 — Password command without password mode

Expected: rejected.

### TP-USEC-001 — Password absence from output and logs

Verify the password does not appear in:

```bash
show console-server user
journalctl
syslog
test output
exception output
```

Document the accepted transient `argv` exposure limitation.

## 13. Interactive connection

### TP-CONN-001 — Connect by line

```bash
connect console-server line 1
```

Expected:

- interactive terminal opens;
- input reaches the attached device;
- output is visible;
- escape sequence disconnects cleanly;
- exit status is propagated.

### TP-CONN-002 — Connect by label

```bash
connect console-server label DUT-CONSOLE-1
```

Expected: resolves to the same physical line.

### TP-CONN-003 — Multiple shared clients

Open clients up to `max_clients`.

Expected: allowed clients connect; session table reflects all clients.

### TP-CONN-004 — Exceed max clients

Attempt one additional connection.

Expected: rejected clearly.

### TP-CONN-005 — Exclusive mode

Set mode to exclusive and attempt a second client.

Expected: second client rejected.

### TP-CNEG-001 — Unknown line

```bash
connect console-server line 999
```

Expected: rejected before launching the interactive client.

### TP-CNEG-002 — Unknown label

Expected: clear error.

### TP-CNEG-003 — Label case sensitivity

Use the correct label with different case.

Expected: no match, because lookup is exact and case-sensitive.

## 14. Session display

### TP-SES-001 — No active sessions

Disconnect all clients:

```bash
show console-server sessions
```

Expected:

```text
No active console-server sessions.
```

### TP-SES-002 — One active session

Connect one client and run the show command.

Expected: one row with correct line, mode, user, role, source IP/port, idle timeout, and time left.

### TP-SES-003 — Multiple clients on one line

Expected: one row per client.

### TP-SES-004 — Multiple lines

Expected: deterministic numeric line ordering.

### TP-SES-005 — Sensitive/internal fields omitted

Expected: no `session_id` or `last_activity` in output.

### TP-SES-006 — Time-left behavior

Wait without activity and repeat the command.

Expected: `Time Left` decreases; activity resets it according to runtime behavior.

### TP-SES-007 — Malformed runtime response

In a controlled fault-injection environment, return malformed JSON.

Expected: clear non-sensitive error; no traceback to the user.

### TP-SES-008 — seriald unavailable

Stop or isolate `seriald` in a controlled test.

Expected: clear failure and nonzero exit.

## 15. ConfigDB persistence and reboot

### TP-PERS-001 — Save configuration

Apply representative port, group, and user metadata changes:

```bash
sudo config save -y
```

Verify the saved configuration contains the console-server tables.

### TP-PERS-002 — Cold reboot persistence

Reboot the DUT.

Expected:

- initialized port rows exist;
- saved user-modified values are preserved according to policy;
- groups and user metadata persist;
- product info is valid;
- runtime and ConfigDB are synchronized;
- show commands succeed.

### TP-PERS-003 — Repeated initialization

Run or trigger initialization more than once.

Expected: idempotent behavior; no duplicate rows; no unintended overwrite.

### TP-PERS-004 — Partial table recovery

Remove one required port row or field, then trigger initialization.

Expected behavior must match the documented repair policy.

## 16. Consistency and failure injection

### TP-FAIL-001 — Runtime update succeeds, ConfigDB port write fails

Inject a ConfigDB write failure.

Expected: runtime rollback attempted; user receives clear error.

### TP-FAIL-002 — Group multi-row write fails midway

Expected: documented behavior; detect partial metadata; runtime compensation attempted; recovery procedure verified.

### TP-FAIL-003 — User application change succeeds, ConfigDB fails

Expected: documented inconsistency; manual recovery steps are usable.

### TP-FAIL-004 — Product cache write fails

Expected: product-info and port display still succeed using live values; subsequent call retries if cache remains absent.

## 17. Performance

Run one cold iteration and five warm iterations on both development and target hardware.

```bash
for i in 1 2 3 4 5; do
    /usr/bin/time -f 'real=%e user=%U sys=%S cpu=%P' \
        show console-server port >/dev/null
done

for i in 1 2 3 4 5; do
    /usr/bin/time -f 'real=%e user=%U sys=%S cpu=%P' \
        show console-server sessions >/dev/null
done
```

Also measure:

```bash
time console-cli show sessions --json >/dev/null
time show console-server product-info >/dev/null
```

Record median, minimum, maximum, CPU utilization, and system load.

Acceptance targets should be agreed for the four-core production platform. Until then, performance is informational unless it causes timeout or usability failure.

## 18. Long-duration and concurrency tests

### TP-STRESS-001 — Repeated show commands

Run show commands in a loop for at least 1,000 iterations.

Expected: no crash, leak, cache corruption, or ConfigDB mutation beyond intended product-info caching.

### TP-STRESS-002 — Concurrent show sessions

Run multiple `show console-server sessions` commands concurrently.

Expected: correct output and no seriald instability.

### TP-STRESS-003 — Concurrent group updates

Only in a controlled environment, issue competing updates to the same group.

Expected: final state is valid and deterministic or conflict behavior is documented.

### TP-STRESS-004 — Session churn

Repeatedly connect and disconnect clients while polling sessions.

Expected: no stale rows after disconnect and no command exceptions.

## 19. Exit criteria

- All automated tests pass.
- All critical functional and negative cases pass.
- No password appears in show output or logs.
- ConfigDB and runtime agree after normal operations and reboot.
- Initialization is idempotent and preserves configuration according to policy.
- All known limitations are documented and accepted.
- Performance on the four-core target is measured and reviewed.
