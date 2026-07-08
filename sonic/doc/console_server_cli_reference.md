# SONiC Console-Server CLI Reference

This section follows the structure used by the SONiC command reference: command description, usage, parameters/options, and examples.

All configuration commands require root privilege. Prefix them with `sudo` or use a root shell. Show and connect commands do not require `sudo` unless restricted by the deployment's local access policy.

All commands and values are case-sensitive unless the command explicitly accepts case-insensitive choices.

## Console-server configuration commands

### config console-server port baudrate

Sets the baud rate of a console line.

- Usage:

```text
config console-server port baudrate <port_number> <rate>
```

- Parameters:
  - `port_number`: Physical console line number.
  - `rate`: Supported baud rate, for example `9600`, `19200`, `38400`, `57600`, or `115200`.

- Example:

```bash
admin@sonic:~$ sudo config console-server port baudrate 1 115200
```

### config console-server port databits

Sets the number of data bits.

- Usage:

```text
config console-server port databits <port_number> <bits>
```

- Parameters:
  - `port_number`: Physical console line number.
  - `bits`: Supported data-bit value.

- Example:

```bash
admin@sonic:~$ sudo config console-server port databits 1 8
```

### config console-server port parity

Sets the parity mode.

- Usage:

```text
config console-server port parity <port_number> <parity>
```

- Parameters:
  - `port_number`: Physical console line number.
  - `parity`: Supported parity mode, such as `none`, `odd`, or `even`.

- Example:

```bash
admin@sonic:~$ sudo config console-server port parity 1 none
```

### config console-server port stopbits

Sets the number of stop bits.

- Usage:

```text
config console-server port stopbits <port_number> <bits>
```

- Example:

```bash
admin@sonic:~$ sudo config console-server port stopbits 1 1
```

### config console-server port flowcontrol

Sets serial flow control.

- Usage:

```text
config console-server port flowcontrol <port_number> <mode>
```

- Parameters:
  - `mode`: Supported flow-control mode, such as `none` or `rtscts`.

- Example:

```bash
admin@sonic:~$ sudo config console-server port flowcontrol 1 none
```

### config console-server port mode

Sets the access mode of a console line.

- Usage:

```text
config console-server port mode <port_number> <mode>
```

- Parameters:
  - `mode`: `shared` or `exclusive`.

- Example:

```bash
admin@sonic:~$ sudo config console-server port mode 1 shared
```

### config console-server port max-clients

Sets the maximum number of simultaneous clients.

- Usage:

```text
config console-server port max-clients <port_number> <count>
```

- Example:

```bash
admin@sonic:~$ sudo config console-server port max-clients 1 4
```

### config console-server port idle-timeout

Sets the client idle timeout in seconds.

- Usage:

```text
config console-server port idle-timeout <port_number> <seconds>
```

- Parameters:
  - `seconds`: `0..86400`. Value `0` disables the timeout.

- Example:

```bash
admin@sonic:~$ sudo config console-server port idle-timeout 1 600
```

### config console-server port label

Sets the unique label of a console line.

- Usage:

```text
config console-server port label <port_number> <label>
```

- Example:

```bash
admin@sonic:~$ sudo config console-server port label 1 TOR-SWITCH-01
```

Labels must be unique. Default labels use the form `COM<port_number>`.

### config console-server group add

Creates a group or replaces its role and complete port membership.

- Usage:

```text
config console-server group add <group_name> <port_list> [--role <role>]
```

- Parameters:
  - `group_name`: Console-server group name.
  - `port_list`: `all`, a line, a range, or a comma-separated combination, for example `1-5,8,10-12`.

- Options:
  - `--role`: `admin`, `console_user`, or `operator`. Default: `console_user`.

- Example:

```bash
admin@sonic:~$ sudo config console-server group add lab 1-5,8 --role console_user
```

### config console-server group delete

Deletes a console-server group and its port membership metadata.

- Usage:

```text
config console-server group delete <group_name>
```

- Example:

```bash
admin@sonic:~$ sudo config console-server group delete lab
```

### config console-server user add

Creates a user or updates an existing user's role, groups, or password.

- Usage:

```text
config console-server user add <username> \
    [--role <role>] \
    [--groups <group_list>] \
    [--password <value> | --prompt-password]
```

- Options:
  - `--role`: `none`, `admin`, `console_user`, or `operator`.
  - `--groups`: Comma-separated existing console-server groups.
  - `--password`: Password for non-interactive automation. It may be visible in shell history and process arguments.
  - `--prompt-password`: Prompt for hidden password input and confirmation.

- Examples:

```bash
admin@sonic:~$ sudo config console-server user add operator1 \
    --role operator \
    --groups lab \
    --prompt-password
```

```bash
admin@sonic:~$ sudo config console-server user add operator1 --groups ops
```

For an existing user, omitted role and groups are preserved. For a new user, an omitted role defaults to `none`.

### config console-server user password

Changes the password of an existing user.

- Usage:

```text
config console-server user password <username> \
    [--password <value> | --prompt-password]
```

- Example:

```bash
admin@sonic:~$ sudo config console-server user password operator1 --prompt-password
```

### config console-server user delete

Deletes a console-server user through the independent application's user-management interface and removes its ConfigDB metadata.

- Usage:

```text
config console-server user delete <username>
```

- Example:

```bash
admin@sonic:~$ sudo config console-server user delete operator1
```

## Console-server show commands

### show console-server port

Displays configured console lines. The TCP port is derived from the product base port and line number.

- Usage:

```text
show console-server port
```

- Example:

```text
admin@sonic:~$ show console-server port
Line  TCP Port  Label  Mode    Max Clients  Idle Timeout  Baudrate  Databits  Stopbits  Parity  Flowcontrol
----  --------  -----  ------  -----------  ------------  --------  --------  --------  ------  -----------
1     35001     COM1   shared  4            600           115200    8         1         none    none
```

The TCP port is calculated as:

```text
tcp_port = base_port + line
```

### show console-server group

Displays configured groups, roles, and permitted console lines.

- Usage:

```text
show console-server group
```

- Example:

```text
admin@sonic:~$ show console-server group
Group  Role          Ports
-----  ------------  -------
lab    console_user  1,2,3,4
```

### show console-server user

Displays non-secret user metadata.

- Usage:

```text
show console-server user
```

- Example:

```text
admin@sonic:~$ show console-server user
Username   Role      Groups
---------  --------  ------
operator1  operator  lab
```

Passwords are never displayed.

### show console-server sessions

Displays active console-server clients.

- Usage:

```text
show console-server sessions
```

- Example:

```text
admin@sonic:~$ show console-server sessions
Line  Mode    User   Role    Client IP      Client Port  Idle Timeout  Time Left
----  ------  -----  ------  -------------  -----------  ------------  ---------
1     shared  admin  writer  10.19.252.103  57050        600           477
1     shared  admin  writer  10.19.252.103  53634        600           518
```

Idle Timeout and Time Left are displayed in seconds. Only active clients are shown.

### show console-server product-info

Displays static product configuration and limits.

- Usage:

```text
show console-server product-info
```

- Example:

```text
admin@sonic:~$ show console-server product-info
Product Configuration & Limits
------------------------------
Base Port  : 35000
Max Ports  : 24
Max Users  : 16
Max Groups : 16
```

The command normally reads `CONSOLE_SERVER_PRODUCT_INFO|global` from ConfigDB. If the entry is missing or invalid, it retrieves product information from the independent application and attempts to cache it.

## Console-server connect commands

### connect console-server line

Connects interactively to a physical console line.

- Usage:

```text
connect console-server line <port_number>
```

- Example:

```bash
admin@sonic:~$ connect console-server line 1
```

The child connection process inherits the terminal's stdin, stdout, and stderr. Use the independent application's configured escape sequence to disconnect.

### connect console-server label

Connects interactively to the line whose configured label exactly matches the supplied label.

- Usage:

```text
connect console-server label <label>
```

- Example:

```bash
admin@sonic:~$ connect console-server label TOR-SWITCH-01
```

Label lookup is exact and case-sensitive.

## Saving configuration

Use the standard SONiC command to persist ConfigDB:

```bash
admin@sonic:~$ sudo config save
```
