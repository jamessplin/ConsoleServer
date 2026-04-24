# Serial Port Configuration


## **Index**
- [1.1. console-cli config port](#11-console-cli-config-port)
- [1.2. console-cli config operation](#12-console-cli-config-operation)
- [1.3. console-cli config save](#13-console-cli-config-save)
- [2.1. console-cli config user add](#21-console-cli-config-user-add)
- [2.2. console-cli config user delete](#22-console-cli-config-user-delete)
- [2.3. console-cli config group add](#23-console-cli-config-group-add)
- [2.4. console-cli config group delete](#24-console-cli-config-group-delete)
- [3.1. console-cli show running-config](#31-console-cli-show-running-config)
- [3.2. console-cli show startup-config](#32-console-cli-show-startup-config)
- [3.3. console-cli show sessions](#33-console-cli-show-sessions)
- [3.4. console-cli show product-info](#34-console-cli-show-product-info)
- [3.5. console-cli connect](#35-console-cli-connect)

---

### 1.1. console-cli config port
**Required Privilege:** console-server or higher (admin)

This command configures the physical serial line settings for a specific port.

```bash
console-cli config port {port_number} [--baudrate <rate>] [--databits <bits>] [--parity <type>] [--stopbits <bits>] [--flowcontrol <method>]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **port_number** | Specifies the serial line number to configure. |
| **--baudrate** | Optional. Sets the baud rate. Supported values: 300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600. |
| --databits | Optional. Sets the data bits. Supported values: 5, 6, 7, 8. |
| --parity | Optional. Sets the parity. Supported values: none, even, odd, mark, space. |
| --stopbits | Optional. Sets the stop bits. Supported values: 1, 2. |
| --flowcontrol| Optional. Sets flow control. Supported values: none, rtscts, xonxoff. |

### **Default**
For a new entry, if a parameter is not specified, the default value is used.
For an existing entry, if a parameter is not specified, its current value is retained.

| Parameter | Default Value |
|---|---|
| --baudrate | 115200 |
| --databits | 8 |
| --parity | none |
| --stopbits | 1 |
| --flowcontrol | none |

### **Usage Guidelines**
Use this command to modify the low-level serial communication parameters for a port. Changes are applied to the running configuration and applied dynamically by restarting the affected serial port service. To persist any changes, use the `config savecommand.

### **Example**
```bash
# Set port 5 to 9600 baud, 8-N-1, with no flow control
> console-cli config port 5 --baudrate 9600 --databits 8 --parity none --stopbits 1 --flowcontrol none

Set serial port configuration    : Success

# Change only the baud rate for port 5
> console-cli config port 5 --baudrate 115200

Set serial port configuration    : Success
```

---

### 1.2. console-cli config operation
**Required Privilege:** console-server or higher (admin)

This command configures the server's operational behavior for a specific serial line.

```bash
console-cli config operation {port_number} [--mode <mode>] [--max-clients <count>] [--idle-timeout <seconds>] [--label <label>]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **port_number** | Specifies the serial line number to configure. |
| **--mode** | Optional. Sets the connection mode (`exclusive`, `shared`). |
| **--max-clients** | Optional. Sets the maximum number of concurrent clients. |
| **--idle-timeout**| Optional. Sets the idle timeout in seconds. Use 0 to disable. |
| **--label**| Optional. Sets a user-friendly nickname for the connected device. |

### **Default**
For a new entry, if a parameter is not specified, the default value is used.
For an existing entry, if a parameter is not specified, its current value is retained.

| Parameter | Default Value |
|---|---|
| --mode | shared |
| --idle-timeout | 600 |
| --label | none |

| Feature | Label |
|---|---|
| Max Length | 16 characters |
| Case Sensitivity | Case-sensitive |

### **Usage Guidelines**
Use this command to control how users interact with a serial line, such as setting the write-access mode and connection limits. Changes are applied to the running configuration and applied dynamically.
**Note:** Changing the `--mode` or `--max-clients` options will restart the serial port service, disconnecting any active clients on that line.
To persist any changes, use the `save-config` command.

### **Example**
```bash
# Set port 5 to shared mode with a 10-minute idle timeout
> console-cli config operation 5 --mode shared --idle-timeout 600

Set serial operation configuration : Success

# Set a new label for port 5
> console-cli config operation 5 --label "BackupConsole"

Set serial operation configuration : Success

# Set the client limit on port 5
> console-cli config operation 5 --max-clients 4

Set serial operation configuration : Success
```

---

### 1.3. console-cli config save
**Required Privilege:** console-server or higher (admin)

This command saves the current running-config to the `config.json` file, making it the new startup-config.

```bash
console-cli config save
```

### **Usage Guidelines**
Use this command to persist any changes made to the running configuration so they will be loaded the next time the `seriald` server starts.

### **Example**
```bash
# Save the current running configuration to disk
> console-cli config save

Configuration saved successfully.
```

---

# 2. User and Group Management

### 2.1. console-cli config user add
**Required Privilege:** admin

This command creates a new user or modifies an existing user's properties.

```bash
console-cli config user add <username> --password <password> [--role <role>] [--groups <group1,group2,...>]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **username** | The name of the user to create or modify. |
| **--role** | Optional. Assigns a specific role to the user (`none`, `operator`, `console_user`, `admin`). This overrides any role inherited from a group. |
| **--groups** | Optional. A comma-separated list of groups to which the user belongs. |
| **--password** | Required. Sets or updates the user password (local Linux account only). |

### **Default**
For a new entry, if a parameter is not specified, the default value is used.
For an existing entry, if a parameter is not specified, its current value is retained.

| Parameter | Default Value |
|---|---|
| --role | none |
| --groups | Group_Default |

### **Usage Guidelines**
- If the user does not exist, this command creates them, and `--password` is required.
- If the user exists, this command modifies their properties.
- Changes are applied to the running configuration. Use `config save` to persist them.

| Feature | Usernames | Passwords |
|---|---|---|
| Max Length | 32 characters  | 128 characters |
| Case Sensitivity | Case-sensitive  | Strictly case-sensitive |
| Starts With | Must be a letter or underscore | Can be anything |

### **Example**
```bash
# Create a new user 'tech1' with the operator role, assigned to 'Group_A'
> console-cli config user add tech1 --role operator --groups Group_A --password tech1

# Create a new user 'guest' with default settings
> console-cli config user add guest --password guest

# Modify user 'tech1' to also be in 'Group_B'
> console-cli config user add tech1 --groups Group_A,Group_B
```

---

### 2.2. console-cli config user delete
**Required Privilege:** admin

This command deletes a user.

```bash
console-cli config user delete <username>
```

### **Parameters**
| Parameter | Description |
|---|---|
| **username** | The name of the user to delete. |

### **Example**
```bash
> console-cli config user delete tech1
```

---

### 2.3. console-cli config group add
**Required Privilege:** admin

This command creates a new group or modifies an existing group's properties.

```bash
console-cli config group add <groupname> [--ports <port1,port2,...>] [--role <role>]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **groupname** | The name of the group to create or modify. |
| **--ports** | Optional. A comma-separated list of serial port numbers to include in this group. |
| **--role** | Optional. Assigns a default role to the group (`operator`, `console_user`, `admin`). |

### **Default**
For a new entry, if a parameter is not specified, the default value is used.
For an existing entry, if a parameter is not specified, its current value is retained.

| Parameter | Default Value |
|---|---|
| --ports | all |
| --role | console_user |

### **Usage Guidelines**
- If the group does not exist, this command creates it.
- If the group exists, this command modifies its properties.
- Port ranges are supported (e.g., `1-5,8,10-12`).
- Changes are applied to the running configuration. Use `config save` to persist them.

| Feature | Group Names |
|---|---|
| Max Length | 32 characters |
| Case Sensitivity | Case-sensitive |

### **Example**
```bash
# Create 'Group_C' with ports 9-12 and an operator role
> console-cli config group add Group_C --ports 9-12 --role operator

# Create a group 'Default_G' with default settings (console_user role, all ports)
> console-cli config group add Default_G

# Add port 13 to 'Group_C'
> console-cli config group add Group_C --ports 9-12,13
```

---

### 2.4. console-cli config group delete
**Required Privilege:** admin

This command deletes a group.

```bash
console-cli config group delete <groupname>
```

### **Parameters**
| Parameter | Description |
|---|---|
| **groupname** | The name of the group to delete. |

### **Example**
```bash
> console-cli config group delete Group_C
```

---

# 3. Show Commands

### 3.1. console-cli show running-config
**Required Privilege:** console-server or higher (admin)

This command displays the current, active (in-memory) configuration of the `seriald` server.

```bash
console-cli show running-config [--line <line_id_or_label>] [--groups] [--users] [--json]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **--line** | Optional. Displays the configuration for a specific serial line, identified by its number (e.g., `5`) or its label (e.g., `"Backup Console"`). Use `all` to display all lines only. |
| **--groups** | Optional. Displays only the `groups` section of the configuration. |
| **--users** | Optional. Displays only the `users` section of the configuration. |
| **--json** | Optional. Outputs raw JSON. If omitted, CLI-friendly output is used. |

### **Usage Guidelines**
Use this command to view the live configuration. By default, it displays the entire configuration. Use the options to filter for specific sections.

### **Example**
```bash
# Show the complete running configuration
> console-cli show running-config

# Show the configuration for line 5
> console-cli show running-config --line 5

# Show the configuration for the line labeled "Backup Console"
> console-cli show running-config --line "Backup Console"

# Show all line entries only
> console-cli show running-config --line all

# Show all line entries as raw JSON
> console-cli show running-config --line all --json

# Show only the groups configuration
> console-cli show running-config --groups

# Show only the users configuration
> console-cli show running-config --users
```

---

### 3.2. console-cli show startup-config
**Required Privilege:** console-server or higher (admin)

This command displays the saved configuration from `config.json` that will be loaded when the `seriald` server starts.

```bash
console-cli show startup-config [--line <line_id_or_label>] [--groups] [--users] [--json]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **--line** | Optional. Displays the configuration for a specific serial line, identified by its number (e.g., `5`) or its label (e.g., `"Backup Console"`). Use `all` to display all lines only. |
| **--groups** | Optional. Displays only the `groups` section of the configuration. |
| **--users** | Optional. Displays only the `users` section of the configuration. |
| **--json** | Optional. Outputs raw JSON. If omitted, CLI-friendly output is used. |

### **Usage Guidelines**
Use this command to verify the configuration that will be applied after a reboot or service restart. By default, it displays the entire configuration.

### **Example**
```bash
# Show the complete startup configuration
> console-cli show startup-config

# Show the startup configuration for line 5
> console-cli show startup-config --line 5

# Show all startup line entries only
> console-cli show startup-config --line all

# Show startup line entries as raw JSON
> console-cli show startup-config --line all --json

# Show only the groups section of the startup configuration
> console-cli show startup-config --groups
```

---

### 3.3. console-cli show sessions
**Required Privilege:** operator or higher (console-server, admin)

This command displays active client sessions connected to the `seriald` server.

```bash
console-cli show sessions [--line <line_id>] [--json]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **--line** | Optional. Filters the output to show session details only for a specific serial line number. |
| **--json** | Optional. Outputs raw JSON. If omitted, CLI-friendly output is used. |

### **Usage Guidelines**
Use this command to get a real-time view of all connected clients. It provides details on which user is connected to which line, their role (writer or observer), and their connection information. This is useful for monitoring server activity and troubleshooting connection issues.

### **Example**
```bash
# Show all active sessions across all lines
> console-cli show sessions

# Show all active sessions as raw JSON
> console-cli show sessions --json

Daemon Sessions:
- line 1 [exclusive] : writer=ted (clients=3, writers=1, observers=2)
    - ted role=writer ip=127.0.0.1 port=40262 [timeout=600s, left=455s]
    - ted role=observer ip=127.0.0.1 port=60854 [timeout=600s, left=502s]
    - alice role=observer ip=127.0.0.1 port=48464 [timeout=600s, left=577s]
- line 2 [shared] : writer=none (clients=0, writers=0, observers=0)

# Show sessions for a specific line
> console-cli show sessions --line 1

Daemon Sessions:
- line 1 [exclusive] : writer=ted (clients=3, writers=1, observers=2)
    - ted role=writer ip=127.0.0.1 port=40262 [timeout=600s, left=455s]
    - ted role=observer ip=127.0.0.1 port=60854 [timeout=600s, left=502s]
    - alice role=observer ip=127.0.0.1 port=48464 [timeout=600s, left=577s]
```

### **Output Field Descriptions**

**Line Summary:**
- `line <id>`: The serial line number.
- `[mode]`: The connection mode for the line (`exclusive` or `shared`).
- `writer`: The username of the client who currently has write permission. `none` if no writer is active.
- `(clients=N, writers=N, observers=N)`: A count of total clients, writers, and observers for the line.

**Client Details (indented):**
- `username`: The name of the connected user.
- `role`: The user's role in the session (`writer` or `observer`).
- `ip`: The IP address of the client.
- `port`: The source port of the client's connection.
- `[timeout=Ns, left=Ns]`: If an idle timeout is configured for the line, this shows the total timeout duration and the remaining time before the client is disconnected due to inactivity.

---

### 3.4. console-cli show product-info
**Required Privilege:** operator or higher (console-server, admin)

This command displays product information, including deployment-specific settings such as the base port and resource limits.

```bash
console-cli show product-info [--json]
```

### **Parameters**
| Parameter | Description |
|---|---|
| **--json** | Optional. Outputs raw JSON. If omitted, CLI-friendly table format is used. |

### **Usage Guidelines**
Use this command to view deployment configuration metadata, such as the base port number and the configured limits for users, groups, and serial ports. This information is read from the `config.json` file and represents the hardware and software constraints for the current deployment.

### **Example**
```bash
# Show product information in table format
> console-cli show product-info
Product Configuration & Limits
------------------------------
Base Port        : 35000
Max Groups       : 16
Max Ports        : 24
Max Users        : 16

# Show product information as raw JSON
> console-cli show product-info --json
{
  "info": {
    "base_port": 35000,
    "no_of_user": 16,
    "no_of_group": 16,
    "no_of_port": 24
  }
}
```

### **Output Field Descriptions**
- `Base Port`: The base port number used for serial connections (typically 35000).
- `Max Users`: The maximum number of users that can be configured in this deployment.
- `Max Groups`: The maximum number of user groups that can be configured in this deployment.
- `Max Ports`: The maximum number of serial ports available in this deployment.

---

### 3.5. console-cli connect
**Required Privilege:** operator or higher (console-server, admin)

This command connects the user's terminal to a specific serial line, allowing direct interaction with the connected device.

```bash
console-cli connect <line_id>
```

### **Parameters**
| Parameter | Description |
|---|---|
| **line_id** | The ID of the serial line to connect to. |

### **Usage Guidelines**
- This command provides a direct, interactive session with the device on the specified serial line.
- The user's ability to get write access depends on their role and the line's current state (e.g., if another writer is already present in `exclusive` mode).
- To exit the session and return to the `console-cli`, type the escape sequence `Ctrl+]`.

### **Example**
```bash
# Connect to line 3 with write access
> console-cli connect 3

[Connecting to line 3. Use Ctrl+] to exit.]
... (serial device output) ...
```
---

### **[Back Page Top](#serial-port-configuration)**
````
