# Console Server Installation and Management Guide

This guide provides instructions for installing, configuring, and managing the `seriald` console server.

## Part 1: Installation

This section covers the initial one-time setup for the console server.

### 1.1 Prerequisites

Before you begin, install the necessary packages on your Debian-based system (e.g., Ubuntu) using `apt`. The `seriald` server requires `ser2net` to manage serial-to-IP connections.

```bash
sudo apt-get update
sudo apt-get install python3-click python3-serial python3-passlib ser2net make
```

### 1.2 Configure the `seriald` Server

The entire `seriald` server and its `ser2net` subprocesses are configured via a single JSON file: `tools/seriald/config.json`. The server reads this file on startup and dynamically generates the required configurations.

A sample configuration for a line looks like this:
```json
"1": {
  "mode": "exclusive",
  "echo": true,
  "window_ms": 800,
  "max_clients": 4,
  "idle_timeout": 600,
  "fakeserial": false,
  "ser2net_host": "127.0.0.1",
  "ser2net_port": 50001,
  "name": "COM1",
  "device": "/dev/ttyUSB0",
  "baudrate": 115200,
  "databits": 8,
  "stopbits": 1,
  "parity": "none",
  "flowcontrol": "none",
  "kickolduser": false
}
```

**Configuration Parameters:**
- `mode`: `exclusive` enforces a single writer; `shared` allows multiple clients to attempt writes.
- `echo`: When `true`, broadcasts writer keystrokes to observers.
- `max_clients`: The maximum number of clients allowed to attach to this line (`null` for unlimited).
- `idle_timeout`: Disconnects clients after this many seconds of inactivity.
- `fakeserial`: Set to `true` for a simulated device for testing. If `false`, the server will attempt to start a real `ser2net` instance.
- `ser2net_port`: The TCP port for `ser2net` to listen on for this line.
- `device`: The path to the serial device file (e.g., `/dev/ttyUSB0`). For devices using a Maxlinear driver, this may be `/dev/ttyXRUSB0`. **Required if `fakeserial` is `false`**.
- `baudrate`, `databits`, `stopbits`, `parity`: Standard serial port settings used to configure the `ser2net` connector.
- `kickolduser`: When `true`, a new connection will disconnect an existing user on the same line if `max-connections` is reached.

### 1.3 Install Helpers and Service

To make the client tools available system-wide and set up the `seriald` service, it is recommended to run the all-in-one `install_helpers.sh` script.

This script will:
1.  Install `seriald-client`, `console-cli`, and `seriald-status` into `/usr/local/bin`.
2.  Copy the `seriald.service` file to `/etc/systemd/system/`.
3.  Reload `systemd`, enable the service to start on boot, and start it immediately.

```bash
sudo ./tools/seriald/install_helpers.sh
```

### 1.4 Manual Installation (Alternative)

If you prefer to install the components manually, follow these steps.

**1. Install Client Helper Scripts:**
```bash
# Install seriald client, console CLI, and status tool into /usr/local/bin
sudo install -m 0755 tools/seriald/client.py /usr/local/bin/seriald-client
sudo install -m 0755 tools/seriald/console_cli.py /usr/local/bin/console-cli
sudo install -m 0755 tools/seriald/status.py /usr/local/bin/seriald-status
sudo install -m 0755 tools/seriald/console-ssh-dispatch.sh /usr/local/bin/console-ssh-dispatch
sudo install -m 0755 tools/seriald/setup_ssh_dispatch.py /usr/local/bin/setup_ssh_dispatch.py
sudo install -m 0755 tools/seriald/server.py /usr/local/bin/server.py
sudo cp -D tools/seriald/config.json /etc/seriald/config.json
```
### 1.5 Initial Server Setup

The `setup_ssh_dispatch.py` script is used for the main setup. It installs the SSH dispatch wrapper, generates the necessary `sshd` configuration, and reloads the SSH service.

Run this command once on a new host to set up the 24-port direct-attach port range. This command splits the ports across two `sshd` instances to stay under the listen-socket limit.

```bash
# Expose ports 20001 through 20024 for IPv4 connections
sudo /usr/local/bin/setup_ssh_dispatch.py -s 20001 -e 20024 \
    --address-family inet \
    --enable-second-sshd \
    --second-sshd-config /etc/ssh/sshd_config_seriald2 \
    --second-sshd-service ssh-seriald2.service
```

This command will:
- Install the `console-ssh-dispatch` wrapper to `/usr/local/bin`.
- Create a primary SSH configuration file at `/etc/ssh/sshd_config.d/console-seriald.conf`.
- Create a secondary SSH configuration file at `/etc/ssh/sshd_config_seriald2`.
- Create, enable, and start a new systemd service named `ssh-seriald2.service` for the secondary SSH instance.
- Reload the main `sshd` service to apply the changes.

**2. Install and Enable the `seriald` Service:**
```bash
# Move the service file to the systemd directory
sudo cp tools/seriald/seriald.service /etc/systemd/system/seriald.service

# Reload the systemd daemon to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable seriald.service
```
After manual installation, you will need to start the service yourself (see Part 2).

## Part 2: Managing the Console Server

Once installed, you can control the `seriald` service with standard `systemctl` commands.

**Starting the Server:**
The service is enabled to start automatically on boot.

> **Note**: If you used the `install_helpers.sh` script as recommended in section 1.4, the service has already been started for you.

If you performed a manual installation, you can start it immediately by running:
```bash
sudo systemctl start seriald.service
```

**Stopping the Server:**
To stop the service gracefully:
```bash
sudo systemctl stop seriald.service
```

**Checking the Status:**
To see the current status, view recent logs, and check for errors:
```bash
sudo systemctl status seriald.service
```

## Part 3: User Management

You can add and remove users who are allowed to access the console server.

### 3.1 Adding a User

To add a new user and set their password, use the `--create-users` and `--password` flags.

```bash
# Add a user named 'alice' with a password
sudo tools/seriald/setup_ssh_dispatch.py --create-users --users alice --password <your_password>
```

- `--create-users`: Creates the user account if it doesn't exist.
- `--password`: Sets the password for the new user. If not provided, the account will be locked.
- The other flags (`--no-install-dispatch`, `--no-fix-include`, `--print-only`) prevent the script from making system changes other than creating the user.

### 3.2 Deleting a User

To delete a user account, use the `--delete-users` flags.

```bash
# Delete the user 'alice' and remove their home directory
sudo tools/seriald/setup_ssh_dispatch.py --delete-users alice --remove-home
```

If the user is currently logged in, you may need to add flags to terminate their sessions:
- `--kill-user-sessions`: Terminates the user's systemd sessions.
- `--kill-processes`: Sends a `SIGTERM` signal to all of the user's processes.
- `--force`: Forces the deletion of the user account.

## Part 4: Usage

### 4.1 Connecting Directly to a Serial Line

Once the server is configured, users can connect directly to a serial line by using the corresponding port number with SSH.

```bash
# Connect to the device on line 1 (port 20001)
ssh -p 20001 <user>@<host>
```

### 4.3 Using the Console CLI

If a user connects to the standard SSH port (22) and is a member of the `console` group, they will be placed in the `console-cli`.

```bash
# Connect to the console CLI
ssh <user>@<host>
```

From within the CLI, you can attach to a serial line via the `seriald` server:

```
# At the CLI prompt:
> sd 1
```

Type `exit` to detach from the line and return to the CLI.

## Part 5: Advanced Configuration

### 5.1 Using a Secondary SSHD for Large Port Ranges

OpenSSH has a limit on the number of listening sockets it can open (typically around 16). If you need to expose a large number of serial ports, you can create a secondary `sshd` instance.

```bash
# Example for ports 20001-20024
sudo tools/seriald/setup_ssh_dispatch.py -s 20001 -e 20024 \
    --address-family inet \
    --enable-second-sshd \
    --second-sshd-config /etc/ssh/sshd_config_seriald2 \
    --second-sshd-service ssh-seriald2.service
```

This will create and enable a new systemd service for the second `sshd` instance.

You can verify the setup with these commands:
```bash
# Check that the service is running
systemctl status ssh-seriald2.service

# Check that ports are listening
ss -lntp | egrep ':20013|:20024'
```

## Part 6: Troubleshooting

If you encounter issues, here are some steps to diagnose the problem.

### 6.1 Checking the `sshd` Configuration

You can test the `sshd` configuration to see what rules are applied for a specific connection.

```bash
# Check the effective config for a user connecting to port 20001
sudo sshd -T -C user=$USER -C lport=20001 | egrep 'forcecommand|permittty'
```
This should show the `ForceCommand` that executes the `console-ssh-dispatch` script.

### 6.2 Checking SSH Logs

The SSH server logs often contain valuable clues.

```bash
# View the latest logs for the main sshd service
journalctl -u sshd -n 100 --no-pager

# View logs for the secondary sshd service
journalctl -u ssh-seriald2.service -f --no-pager
```

### 6.3 Lingering Sessions

If a user disconnects abruptly, their session may linger for a short time. The `seriald` server has a keepalive mechanism to automatically clean up these sessions. You can also check the status of clients with `seriald-status`.

```bash
# If installed via the helper script
seriald-status
```

## Part 7: Verification and Troubleshooting

If you encounter issues, here are some steps to diagnose the problem.

### 7.1 Verify `ser2net` Processes

After starting the server, you can verify that the `ser2net` processes were launched correctly.

```bash
ps -aux | grep ser2net
```

You should see one `ser2net` process for each line configured with `"fakeserial": false`. These processes should be running as the `root` user, which is required for them to access serial device files.

### 7.2 Test Connection with Telnet

You can perform a quick connection test using `telnet`.

```bash
# Connect to the ser2net port for line 1 (e.g., 50001)
telnet localhost 50001
```

If the connection is successful, you should see a banner from `ser2net`. If it fails with "Permission denied," it likely means the `ser2net` process does not have the necessary privileges to open the serial device (e.g., `/dev/ttyUSB0`). Ensure you are running the `seriald_boot_init.sh` script, which handles the `sudo` execution.

## Part 8: Uninstalling System Integration

If you need to fully remove all system integration (users, groups, SSH/systemd configs, and services) created by the console server setup, use the `--remove-all` option with the setup script. This will clean up all system-level changes made by previous setup or user management commands, but will not delete the application source code or your configuration files.

### 8.1 Full Uninstall Example

```bash
sudo tools/seriald/setup_ssh_dispatch.py --remove-all
```

- This command removes all users, groups, SSHD/systemd configs, and services created by the script.
- It does NOT remove the application source code or your own configuration files.
- You can add `--dry-run` to preview what would be removed without making changes:

```bash
sudo tools/seriald/setup_ssh_dispatch.py --remove-all --dry-run
```

> **Warning:** This is the recommended and safest way to uninstall all system integration. Do not manually delete users or configs unless you know exactly what was created.
