# SONiC ConsoleServer CLI Reference

This document describes the SONiC ConsoleServer commands, their parameters, update semantics, and representative output.

All configuration commands require root privilege. Prefix them with `sudo` or run them from a root shell. Show and connect commands do not require `sudo` unless restricted by the deployment's access policy.

Commands, labels, user names, and group names are case-sensitive unless stated otherwise.

## 1. Port Configuration Commands

### 1.1 `config console-server port baudrate`

Sets the baud rate of a console line.

**Usage**

```text
config console-server port baudrate <port_number> <rate>
```

**Parameters**

- `port_number`: Physical console line number.
- `rate`: Supported baud rate, such as `9600`, `19200`, `38400`, `57600`, or `115200`.

**Example**

```bash
admin@sonic:~$ sudo config console-server port baudrate 1 115200
```

### 1.2 `config console-server port databits`

Sets the number of data bits for a console line.

**Usage**

```text
config console-server port databits <port_number> <bits>
```

**Parameters**

- `port_number`: Physical console line number.
- `bits`: Supported data-bit value.

**Example**

```bash
admin@sonic:~$ sudo config console-server port databits 1 8
```

### 1.3 `config console-server port parity`

Sets the parity mode of a console line.

**Usage**

```text
config console-server port parity <port_number> <parity>
```

**Parameters**

- `port_number`: Physical console line number.
- `parity`: Supported parity mode, such as `none`, `odd`, or `even`.

**Example**

```bash
admin@sonic:~$ sudo config console-server port parity 1 none
```

### 1.4 `config console-server port stopbits`

Sets the number of stop bits for a console line.

**Usage**

```text
config console-server port stopbits <port_number> <bits>
```

**Parameters**

- `port_number`: Physical console line number.
- `bits`: Supported stop-bit value.

**Example**

```bash
admin@sonic:~$ sudo config console-server port stopbits 1 1
```

### 1.5 `config console-server port flowcontrol`

Sets serial flow control for a console line.

**Usage**

```text
config console-server port flowcontrol <port_number> <mode>
```

**Parameters**

- `port_number`: Physical console line number.
- `mode`: Supported flow-control mode, such as `none` or `rtscts`.

**Example**

```bash
admin@sonic:~$ sudo config console-server port flowcontrol 1 none
```

### 1.6 `config console-server port mode`

Sets the access mode of a console line.

**Usage**

```text
config console-server port mode <port_number> <mode>
```

**Parameters**

- `port_number`: Physical console line number.
- `mode`: `shared` or `exclusive`.

**Example**

```bash
admin@sonic:~$ sudo config console-server port mode 1 shared
```

### 1.7 `config console-server port max-clients`

Sets the maximum number of simultaneous clients allowed on a console line.

**Usage**

```text
config console-server port max-clients <port_number> <count>
```

**Parameters**

- `port_number`: Physical console line number.
- `count`: Maximum simultaneous client count supported by the product.

**Example**

```bash
admin@sonic:~$ sudo config console-server port max-clients 1 4
```

### 1.8 `config console-server port idle-timeout`

Sets the client idle timeout in seconds.

**Usage**

```text
config console-server port idle-timeout <port_number> <seconds>
```

**Parameters**

- `port_number`: Physical console line number.
- `seconds`: `0..86400`; `0` disables the idle timeout.

**Example**

```bash
admin@sonic:~$ sudo config console-server port idle-timeout 1 600
```

### 1.9 `config console-server port label`

Sets the unique label of a console line.

**Usage**

```text
config console-server port label <port_number> <label>
```

**Parameters**

- `port_number`: Physical console line number.
- `label`: Unique, case-sensitive line label.

**Example**

```bash
admin@sonic:~$ sudo config console-server port label 1 TOR-SWITCH-01
```

Default labels use the form `COM<port_number>`. A label already assigned to another line is rejected.

## 2. Group Configuration Commands

### 2.1 `config console-server group add`

Creates a ConsoleServer group or replaces an existing group's role and complete port membership.

**Usage**

```text
config console-server group add <group_name> <port_list> [--role <role>]
```

**Parameters**

- `group_name`: ConsoleServer group name.
- `port_list`: `all`, one line, one range, or a comma-separated combination such as `1-5,8,10-12`.

**Options**

- `--role`: `admin`, `console_user`, or `operator`. Default: `console_user`.

**Example**

```bash
admin@sonic:~$ sudo config console-server group add lab 1-5,8 --role console_user
```

Running the command for an existing group replaces both its role and its complete membership. Ports omitted from the new `port_list` are removed from the group.

### 2.2 `config console-server group delete`

Deletes a ConsoleServer group and its port-membership metadata.

**Usage**

```text
config console-server group delete <group_name>
```

**Example**

```bash
admin@sonic:~$ sudo config console-server group delete lab
```

## 3. User Configuration Commands

Linux/NSS is authoritative for user accounts and passwords. ConfigDB stores only non-secret ConsoleServer role and group metadata.

### 3.1 `config console-server user add`

Creates a Linux/NSS user for ConsoleServer access or updates an existing user's ConsoleServer role, group membership, or password.

**Usage**

```text
config console-server user add <username> \
    [--role <role>] \
    [--groups <group_list>] \
    [--password <value> | --prompt-password]
```

**Options**

- `--role`: `none`, `admin`, `console_user`, or `operator`.
- `--groups`: Comma-separated list of existing ConsoleServer groups.
- `--password`: Password for non-interactive use. The value may be visible in shell history and briefly visible to privileged process inspection.
- `--prompt-password`: Prompts for hidden password entry and confirmation.

**Examples**

```bash
admin@sonic:~$ sudo config console-server user add operator1 \
    --role operator \
    --groups lab \
    --prompt-password
```

```bash
admin@sonic:~$ sudo config console-server user add operator1 --groups ops
```

For an existing user:

- omitted `--role` preserves the existing ConsoleServer role;
- omitted `--groups` preserves the existing ConsoleServer group memberships;
- omitting a password preserves the current Linux/NSS password.

For a new user, an omitted role defaults to `none`.

### 3.2 `config console-server user password`

Changes the Linux/NSS password of an existing ConsoleServer user.

**Usage**

```text
config console-server user password <username> \
    [--password <value> | --prompt-password]
```

**Example**

```bash
admin@sonic:~$ sudo config console-server user password operator1 --prompt-password
```

The command changes only password state. ConsoleServer role and group metadata remain unchanged.

### 3.3 `config console-server user delete`

Deletes the Linux/NSS user and removes the associated non-secret ConsoleServer metadata from ConfigDB.

**Usage**

```text
config console-server user delete <username>
```

**Example**

```bash
admin@sonic:~$ sudo config console-server user delete operator1
```

## 4. Show Commands

### 4.1 `show console-server port`

Displays configured console lines. The TCP port is derived from the product base port and line number.

**Usage**

```text
show console-server port
```

**Example**

```text
admin@sonic:~$ show console-server port
Line  TCP Port  Label  Mode    Max Clients  Idle Timeout  Baudrate  Databits  Stopbits  Parity  Flowcontrol
----  --------  -----  ------  -----------  ------------  --------  --------  --------  ------  -----------
1     35001     COM1   shared  4            600           115200    8         1         none    none
```

### 4.2 `show console-server group`

Displays configured ConsoleServer groups, roles, and permitted console lines.

**Usage**

```text
show console-server group
```

**Example**

```text
admin@sonic:~$ show console-server group
Group  Role          Ports
-----  ------------  -------
lab    console_user  1,2,3,4
```

### 4.3 `show console-server user`

Displays non-secret ConsoleServer user metadata.

**Usage**

```text
show console-server user
```

**Example**

```text
admin@sonic:~$ show console-server user
Username   Role      Groups
---------  --------  ------
operator1  operator  lab
```

Passwords and password hashes are never displayed.

### 4.4 `show console-server sessions`

Displays active ConsoleServer clients reported by the running ConsoleServer.

**Usage**

```text
show console-server sessions
```

**Example**

```text
admin@sonic:~$ show console-server sessions
Line  Mode    User   Role      Client IP      Client Port  Idle Timeout  Time Left
----  ------  -----  --------  -------------  -----------  ------------  ---------
1     shared  admin  writer    10.19.252.103  57050        600           477
1     shared  admin  observer  10.19.252.104  53634        600           518
```

Idle Timeout and Time Left are displayed in seconds. Each active client is displayed as one row. Lines without active clients are omitted.

### 4.5 `show console-server product-info`

Displays read-only ConsoleServer product limits.

**Usage**

```text
show console-server product-info
```

**Example**

```text
admin@sonic:~$ show console-server product-info
Product Configuration & Limits
------------------------------
Base Port  : 35000
Max Ports  : 24
Max Users  : 16
Max Groups : 16
```

## 5. Connect Commands

### 5.1 `connect console-server line`

Connects interactively to a physical console line.

**Usage**

```text
connect console-server line <port_number>
```

**Parameters**

- `port_number`: Physical console line number.

**Example**

```bash
admin@sonic:~$ connect console-server line 1
```

The command validates the line and starts the supported interactive connection path. The connection process inherits the terminal's standard input, output, and error streams.

Use the ConsoleServer connection escape sequence to disconnect.

### 5.2 `connect console-server label`

Connects interactively to the line whose configured label exactly matches the supplied label.

**Usage**

```text
connect console-server label <label>
```

**Parameters**

- `label`: Existing case-sensitive ConsoleServer line label.

**Example**

```bash
admin@sonic:~$ connect console-server label TOR-SWITCH-01
```

Label lookup is exact and case-sensitive.

## 6. Saving Configuration

Use the standard SONiC command to persist ConfigDB:

```bash
admin@sonic:~$ sudo config save
```

No ConsoleServer-specific save command is required.

`/run/seriald/config.json` is a generated startup snapshot and is not used as the persistence source for `config save`.
