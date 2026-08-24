# SONiC ConsoleServer CLI User Test Plan

**Target release:** SONiC 202511  
**Test perspective:** SONiC administrator or operator  
**Test interface:** SONiC `config`, `show`, and `connect` commands

---

# 1. Purpose

This document verifies the ConsoleServer feature from a SONiC user's point of view.

The tester is not expected to know how the feature is implemented internally. The tests use only the public SONiC CLI and user-observable behavior.

The plan verifies that a user can:

- find the ConsoleServer commands;
- view product and console-line information;
- configure console lines;
- create and manage groups;
- create and manage users;
- connect to console lines by line number or label;
- view active sessions;
- save configuration and retain it after reboot;
- receive clear errors for invalid commands or values;
- use the feature without exposing passwords.

# 2. Test Environment

Record the following information before testing:

```text
SONiC image/version:
Platform/HwSKU:
Number of console lines:
Attached devices:
Remote test clients:
Tester:
Date:
```

The tester needs:

- access to the SONiC CLI;
- administrator privilege for configuration commands;
- at least one console line connected to a working serial device;
- a second terminal or client for multiple-session tests;
- permission to reboot the system for persistence testing.

Use temporary test names that will not affect production users or groups. Suggested names:

```text
Port label: TEST-CONSOLE-1
Group:      test-group
User:       cs_test1
```

---

# 3. CLI Availability and Help

## TP-CLI-001 — Verify root commands

Run:

```bash
config --help
show --help
connect --help
```

Expected:

- `console-server` appears under `config`;
- `console-server` appears under `show`;
- `console-server` appears under `connect`.

## TP-CLI-002 — Verify ConsoleServer help

Run:

```bash
config console-server --help
show console-server --help
connect console-server --help
```

Expected:

- each command completes without error;
- available subcommands are listed;
- help text is understandable and contains no Python traceback.

## TP-CLI-003 — Verify configuration privilege

Run one harmless configuration command without `sudo` or root privilege.

Expected:

- the command is rejected clearly when administrator privilege is required;
- the current configuration remains unchanged.

---

# 4. Product Information

## TP-PROD-001 — Show product information

Run:

```bash
show console-server product-info
```

Expected:

- the command succeeds;
- the output shows:
  - base TCP port;
  - maximum console ports;
  - maximum users;
  - maximum groups;
- values match the product specification;
- values are displayed as read-only information.

## TP-PROD-002 — Repeat product-information display

Run the command several times:

```bash
show console-server product-info
```

Expected:

- the displayed values remain consistent;
- repeated use does not produce errors;
- no configuration command is required before product information can be displayed.

---

# 5. Console-Line Display

## TP-PORT-001 — Show all console lines

Run:

```bash
show console-server port
```

Expected:

- all supported console lines appear;
- lines are listed in numeric order;
- each row shows the available serial and access settings;
- each row shows a label;
- each row shows a TCP port;
- no duplicate line number or label appears.

## TP-PORT-002 — Verify TCP-port sequence

From the product information, note the base TCP port.

Verify several rows in:

```bash
show console-server port
```

Expected:

```text
TCP port = base port + console line number
```

For example, when the base port is `35000`:

```text
Line 1  → TCP port 35001
Line 24 → TCP port 35024
```

## TP-PORT-003 — Verify default labels

Check lines that have not been renamed.

Expected:

```text
COM1
COM2
...
```

Each default label belongs to its corresponding console line.

---

# 6. Console-Line Configuration

Before each test, record the original value from:

```bash
show console-server port
```

After the test, restore the original value when practical.

## TP-PCFG-001 — Set baud rate

Run:

```bash
sudo config console-server port baudrate 1 9600
show console-server port
```

Expected:

- the command succeeds;
- line 1 shows baud rate `9600`;
- unrelated settings remain unchanged.

## TP-PCFG-002 — Set data bits

Run:

```bash
sudo config console-server port databits 1 8
show console-server port
```

Expected: line 1 shows data bits `8`.

## TP-PCFG-003 — Set parity

Run:

```bash
sudo config console-server port parity 1 none
show console-server port
```

Expected: line 1 shows parity `none`.

## TP-PCFG-004 — Set stop bits

Run:

```bash
sudo config console-server port stopbits 1 1
show console-server port
```

Expected: line 1 shows one stop bit.

## TP-PCFG-005 — Set flow control

Run:

```bash
sudo config console-server port flowcontrol 1 none
show console-server port
```

Expected: line 1 shows flow control `none`.

## TP-PCFG-006 — Set shared mode

Run:

```bash
sudo config console-server port mode 1 shared
show console-server port
```

Expected: line 1 shows mode `shared`.

## TP-PCFG-007 — Set exclusive mode

Run:

```bash
sudo config console-server port mode 1 exclusive
show console-server port
```

Expected: line 1 shows mode `exclusive`.

Restore shared mode before the multiple-client tests if required.

## TP-PCFG-008 — Set maximum clients

Run:

```bash
sudo config console-server port max-clients 1 4
show console-server port
```

Expected: line 1 shows maximum clients `4`.

## TP-PCFG-009 — Set idle timeout

Run:

```bash
sudo config console-server port idle-timeout 1 600
show console-server port
```

Expected: line 1 shows idle timeout `600` seconds.

## TP-PCFG-010 — Disable idle timeout

Run:

```bash
sudo config console-server port idle-timeout 1 0
show console-server port
```

Expected:

- the command succeeds;
- the displayed value is `0`;
- idle timeout is disabled for the line.

## TP-PCFG-011 — Set a label

Run:

```bash
sudo config console-server port label 1 TEST-CONSOLE-1
show console-server port
```

Expected:

- line 1 shows `TEST-CONSOLE-1`;
- the label appears only once;
- other lines keep their existing labels.

## TP-PCFG-012 — Repeat the current value

Set one field to the value it already has.

Expected:

- the command succeeds;
- the displayed configuration remains correct;
- no user-visible disruption occurs.

---

# 7. Invalid Console-Line Inputs

For every rejected command, verify afterward that the previous configuration is unchanged.

## TP-PNEG-001 — Line number below range

```bash
sudo config console-server port baudrate 0 9600
```

Expected: clear error; no configuration change.

## TP-PNEG-002 — Line number above product limit

For a 24-line product:

```bash
sudo config console-server port baudrate 25 9600
```

Expected: clear error; no configuration change.

## TP-PNEG-003 — Unsupported baud rate

```bash
sudo config console-server port baudrate 1 12345
```

Expected: clear error showing or implying the supported values.

## TP-PNEG-004 — Invalid parity

```bash
sudo config console-server port parity 1 invalid
```

Expected: clear error; no configuration change.

## TP-PNEG-005 — Invalid access mode

```bash
sudo config console-server port mode 1 invalid
```

Expected: clear error; no configuration change.

## TP-PNEG-006 — Idle timeout above limit

```bash
sudo config console-server port idle-timeout 1 86401
```

Expected: clear error; no configuration change.

## TP-PNEG-007 — Duplicate label

Assign line 2 the same custom label used by line 1.

Expected:

- the command is rejected;
- each line keeps its original label.

## TP-PNEG-008 — Reserved default-label conflict

Try to assign a default label such as `COM2` to the wrong line.

Expected:

- the command is rejected;
- default-label ownership remains valid.

---

# 8. Group Configuration

## TP-GRP-001 — Create a group

Run:

```bash
sudo config console-server group add test-group 1-3 --role console_user
show console-server group
```

Expected:

- `test-group` appears;
- role is `console_user`;
- ports are shown as `1,2,3` or an equivalent normalized form.

## TP-GRP-002 — Replace group membership

Run:

```bash
sudo config console-server group add test-group 2,4,6 --role operator
show console-server group
```

Expected:

- role changes to `operator`;
- membership becomes exactly `2,4,6`;
- old members `1` and `3` are no longer shown.

## TP-GRP-003 — Create a group using `all`

Run:

```bash
sudo config console-server group add all-test-lines all
show console-server group
```

Expected: the group contains every supported console line.

## TP-GRP-004 — Repeat the current group definition

Run the same group command again with the same role and ports.

Expected:

- the command succeeds;
- the group remains unchanged;
- no user-visible disruption occurs.

## TP-GRP-005 — Delete a group

Run:

```bash
sudo config console-server group delete test-group
show console-server group
```

Expected:

- `test-group` no longer appears;
- unrelated groups remain unchanged.

## TP-GNEG-001 — Unknown console line

```bash
sudo config console-server group add bad-group 999
```

Expected: clear error; group is not created.

## TP-GNEG-002 — Malformed port list

```bash
sudo config console-server group add bad-group 1-3,,5
```

Expected: clear error; group is not created.

## TP-GNEG-003 — Unsupported role

```bash
sudo config console-server group add bad-group 1 --role observer
```

Expected: clear error; group is not created.

## TP-GNEG-004 — Delete a nonexistent group

```bash
sudo config console-server group delete no-such-group
```

Expected: clear and predictable result; unrelated groups remain unchanged.

---

# 9. User Configuration

Use a temporary user account such as `cs_test1`.

## TP-USR-001 — Create a user with hidden password entry

First create or verify a test group, then run:

```bash
sudo config console-server user add cs_test1 \
    --role operator \
    --groups all-test-lines \
    --prompt-password
```

Expected:

- password input is hidden;
- password confirmation is requested;
- the command succeeds when both entries match;
- the user appears in `show console-server user`;
- role and group are correct;
- the password is not displayed.

## TP-USR-002 — Update only the role

Run:

```bash
sudo config console-server user add cs_test1 --role admin
show console-server user
```

Expected:

- role changes to `admin`;
- existing groups remain unchanged;
- existing password still works.

## TP-USR-003 — Update only the groups

Run:

```bash
sudo config console-server user add cs_test1 --groups all-test-lines
show console-server user
```

Expected:

- groups change as requested;
- the current role remains unchanged;
- the current password remains unchanged.

## TP-USR-004 — Change only the password

Run:

```bash
sudo config console-server user password cs_test1 --prompt-password
```

Expected:

- password input is hidden;
- role and groups remain unchanged;
- the new password works;
- the old password no longer works.

## TP-USR-005 — Show user metadata

Run:

```bash
show console-server user
```

Expected:

- username, role, and groups are shown;
- no password or password hash is shown.

## TP-USR-006 — Delete a user

Run:

```bash
sudo config console-server user delete cs_test1
show console-server user
```

Expected:

- the user no longer appears;
- the deleted credentials no longer provide access;
- unrelated users remain unchanged.

## TP-UNEG-001 — Conflicting password options

Use `--password` and `--prompt-password` together.

Expected: command is rejected before the user is changed.

## TP-UNEG-002 — Unknown group

Try to create or update a user with a group that does not exist.

Expected: clear error; user state remains unchanged.

## TP-UNEG-003 — Password command without a password option

Run a password command without `--password` or `--prompt-password`.

Expected: clear usage error; password remains unchanged.

## TP-UNEG-004 — Invalid role

Try to assign an unsupported role.

Expected: clear error; user state remains unchanged.

## TP-USEC-001 — Verify passwords are not exposed

After user operations, check normal user-visible output:

```bash
show console-server user
```

Expected:

- no password appears;
- no password hash appears;
- command errors do not repeat the password.

---

# 10. Interactive Connection

These tests require a serial device attached to at least one console line.

## TP-CONN-001 — Connect by line number

Run:

```bash
connect console-server line 1
```

Expected:

- an interactive session opens;
- serial output from the attached device is visible;
- keyboard input reaches the attached device;
- the documented escape sequence closes the session cleanly.

## TP-CONN-002 — Connect by label

After assigning `TEST-CONSOLE-1` to line 1, run:

```bash
connect console-server label TEST-CONSOLE-1
```

Expected: the connection opens to the same physical line as line number `1`.

## TP-CONN-003 — Shared-mode clients

Configure line 1 for shared mode and a maximum of at least two clients.

Open two connections from separate terminals.

Expected:

- both permitted clients connect;
- both can see device output according to the product's shared-mode behavior;
- active sessions appear in the session display.

## TP-CONN-004 — Maximum-client limit

Open connections up to the configured maximum, then attempt one more.

Expected:

- connections up to the limit succeed;
- the extra connection is rejected clearly.

## TP-CONN-005 — Exclusive mode

Configure line 1 for exclusive mode.

Open one connection, then attempt a second.

Expected:

- the first connection succeeds;
- the second connection is rejected while the first is active.

## TP-CNEG-001 — Unknown line

```bash
connect console-server line 999
```

Expected: clear error; no connection process starts.

## TP-CNEG-002 — Unknown label

```bash
connect console-server label NO-SUCH-LABEL
```

Expected: clear error; no connection process starts.

## TP-CNEG-003 — Label case sensitivity

Use the correct label with different letter case.

Expected: it does not match when label lookup is case-sensitive.

---

# 11. Active Session Display

## TP-SES-001 — No active sessions

Close all console connections, then run:

```bash
show console-server sessions
```

Expected: a clear message indicates that no active sessions exist.

## TP-SES-002 — One active session

Open one console connection from another terminal, then run:

```bash
show console-server sessions
```

Expected: one row appears with user-visible session information such as:

- line;
- access mode;
- user;
- role;
- client address and port;
- idle timeout;
- remaining time.

## TP-SES-003 — Multiple clients on one line

Open multiple permitted clients on the same shared line.

Expected: one row is shown for each active client.

## TP-SES-004 — Multiple active lines

Open sessions on more than one console line.

Expected:

- all active sessions are shown;
- lines are displayed in predictable numeric order.

## TP-SES-005 — Internal information is hidden

Expected: internal identifiers or implementation-only timestamps are not shown.

## TP-SES-006 — Idle-time countdown

With a nonzero idle timeout, leave a session inactive and repeat:

```bash
show console-server sessions
```

Expected:

- remaining time decreases while idle;
- activity resets the timer according to the configured behavior;
- the session closes when the timeout expires.

## TP-SES-007 — Runtime unavailable

When permitted in a maintenance environment, stop or restart the ConsoleServer service and run:

```bash
show console-server sessions
```

Expected:

- a clear user-facing error is shown;
- no Python traceback is displayed.

---

# 12. Save, Reboot, and Service Restart

## TP-PERS-001 — Save configuration

Apply representative port, group, and user metadata changes, then run:

```bash
sudo config save -y
```

Expected: the standard SONiC save command succeeds.

## TP-PERS-002 — Reboot persistence

After saving, reboot the system.

Run:

```bash
show console-server port
show console-server group
show console-server user
show console-server product-info
```

Expected:

- saved port settings remain;
- saved labels remain;
- saved groups and memberships remain;
- saved non-secret user metadata remains;
- product information displays correctly;
- console connections work after startup.

## TP-PERS-003 — Service restart

Restart the ConsoleServer service during a maintenance window.

After restart, run the show and connect commands again.

Expected:

- the service returns to operation;
- saved configuration is applied;
- users can reconnect;
- no unexpected duplicate or missing console lines appear.

## TP-PERS-004 — Unsaved change behavior

Make a test configuration change but do not run `config save`.

Reboot the system only when it is safe to do so.

Expected: behavior matches standard SONiC unsaved-configuration behavior.

---

# 13. Usability and Stability

## TP-USE-001 — Repeated show commands

Run each command repeatedly:

```bash
show console-server port
show console-server group
show console-server user
show console-server sessions
show console-server product-info
```

Expected:

- output remains consistent;
- commands do not crash;
- no traceback appears;
- response time remains acceptable for interactive use.

## TP-USE-002 — Concurrent session display

From several terminals, run:

```bash
show console-server sessions
```

Expected: each command returns correct output without disrupting active console sessions.

## TP-USE-003 — Session connect/disconnect cycles

Repeatedly connect to and disconnect from a console line while checking session display.

Expected:

- new sessions appear promptly;
- closed sessions disappear;
- stale session rows are not retained.

## TP-USE-004 — Clear error messages

Review errors produced by invalid port, group, user, and connect tests.

Expected:

- messages identify the problem clearly;
- messages do not expose internal stack traces;
- messages do not expose passwords or other secrets.

---

# 14. Test Completion Criteria

Testing is complete when:

- all ConsoleServer command groups are available;
- all supported port settings can be changed and displayed;
- invalid port values are rejected without changing the configuration;
- groups can be created, replaced, displayed, and deleted;
- users can be created, updated, displayed, and deleted;
- passwords are not exposed in normal output or errors;
- connection by line and label works;
- shared, exclusive, maximum-client, and idle-timeout behavior work as documented;
- active sessions are displayed correctly;
- saved configuration survives reboot;
- service restart restores usable operation;
- no critical unexplained errors, crashes, or tracebacks remain;
- hardware-dependent results are recorded for the target platform.

Record any failed or blocked test with:

```text
Test ID:
Result: Pass / Fail / Blocked
Observed behavior:
Expected behavior:
Logs or screenshots:
Follow-up owner:
```
