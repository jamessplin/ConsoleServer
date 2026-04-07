# Requirement Specification: Console Server Share Mode

This document outlines the requirements and implementation plan for enabling a real-time, multi-user shared console session.

## 1. Core Requirements

1.  **Real-time Keystroke Broadcasting**: Any character typed by the "active" client (the writer) must be immediately visible on the terminals of all "passive" clients (the observers) connected to the same serial line. Input should not be buffered until a newline is sent.
2.  **No Double Echo**: The active client must only see a single echo of the characters they type. Characters should not be echoed twice (e.g., once locally and once from the remote device).

## 2. Architecture Overview

To achieve resilience, scalability, and prevent a single point of failure, the system will use a separated **Control Plane** and **Data Plane** architecture.

*   **Control Plane (`server.py`)**: Manages client connections, roles (`writer`/`observer`), and the line mode (`shared`/`exclusive`). It strictly enforces the single-writer rule in `exclusive` mode. The server also connects to the `ser2net` data plane to read all device output and broadcast it to every connected client, ensuring all users see the same console state.
*   **Data Plane (`ser2net` and `client.py`)**: The `client.py` instance with the "writer" role (in either mode) establishes a direct connection to the `ser2net` backend for the actual serial data I/O. This is the primary, low-latency path for sending input to the end device.

## 3. Implementation Details & Files to Modify

### 3.1. SSH Server Configuration (`/etc/ssh/sshd_config`)

*   **Purpose**: To allow the client-side application to allocate a pseudo-terminal (PTY), which is required for capturing individual keystrokes in "raw" terminal mode.
*   **Change**: Within the relevant `Match` block for the console service, the `PermitTTY` directive must be enabled.
    ```diff
    Match LocalPort 20001
        ForceCommand /usr/bin/console-ssh-dispatch
    -   PermitTTY no
    +   PermitTTY yes
    ```
*   **Action**: This change must be applied by a system administrator on the server running `sshd`, followed by a restart of the SSH service.

### 3.2. ser2net Configuration (`/etc/ser2net.conf` or YAML equivalent)

*   **Purpose**: To provide a Telnet-based stream connected to the serial port, which allows for proper out-of-band signaling (like BREAK) and robust session negotiation.
*   **Change**: The `ser2net` connector must be configured as a `telnet` listener. This ensures that Telnet command sequences sent by the client are correctly interpreted by the server.

    **Example of a Correct Configuration (YAML format for ser2net v4+):**
    ```yaml
    connection: &con_template
        accepter: telnet,50001
        connector: serialdev,/dev/ttyUSB0,115200n81
    ```
*   **Action**: A system administrator must ensure the `ser2net` configuration uses a `telnet` accepter and restart the service if any changes are made. The port number will be assigned by the `seriald` server.

### 3.3. Console Client (`tools/seriald/client.py`)

*   **Purpose**: To handle control/data plane connections, raw terminal I/O, and role-based logic.
*   **Changes**:
    1.  **Establish Two Connections**: Connect to `server.py` (control plane) to get role, mode, and the `ser2net` port. Then, open a second connection to that `ser2net` port (data plane).
    2.  **Enable and Restore Raw Terminal Mode**: Use `tty` and `termios` to capture single keystrokes. The client MUST ensure that it restores the original terminal settings in a `finally` block, so that the user's shell is usable after the client exits, regardless of whether it exits cleanly or via an error.
    3.  **Perform Telnet Negotiation**: Immediately after connecting to the `ser2net` Telnet port, the client performs a negotiation (`IAC WONT ECHO`, `IAC DONT SGA`, etc.) to establish a clean data stream. This ensures the client has full control over line discipline and prevents the server from echoing characters, which is critical for the single-echo requirement.
    4.  **Implement Role and Mode-Based Logic**: The client's behavior depends on its role, which is assigned by the server.
        *   **If `writer` (in either `shared` or `exclusive` mode)**: The `stdin_reader` sends every keystroke **only** to the direct `ser2net` data plane connection. The echo seen by the user is the one that comes back from the end device.
        *   **If `observer`**: The `stdin_reader` is disabled, as observers cannot type.
    5.  **Update Readers**: The `data_plane_reader` reads from the `ser2net` connection and prints to `stdout`. The `control_plane_handler` reads from the `server.py` connection for control messages (like role changes).

### 3.4. Console Server (`tools/seriald/server.py`)

*   **Purpose**: To act as the central Control Plane manager and data broadcaster.
*   **Changes**:
    1.  **Connect to Data Plane**: For each active line with a real device, the server establishes its own connection to the `ser2net` port.
    2.  **Read and Broadcast**: The server continuously reads the output from the `ser2net` port (which includes device echoes and command results) and broadcasts this data to **all** clients (writers and observers) on that line.
    3.  **Enforce Writer Role**: The server manages who has the `writer` role. In `exclusive` mode, it ensures only one client is the writer at any time. In `shared` mode, it allows any client to be a writer. The server does **not** receive or echo input from clients for real devices; its job is to broadcast the device's own output.

## 4. User-Side Client Configuration

To prevent a "double echo" effect, users connecting with terminal applications like PuTTY, TeraTerm, or MobaXterm must disable the "local echo" feature within their client. The server-side `PermitTTY yes` setting enables raw mode but does not control the client's local settings.

If local echo is enabled, users will see every character they type twice: once instantly from their own terminal, and a second time after the character has been processed by the server.

### 4.1. PuTTY

1.  Navigate to the **Terminal** -> **Line discipline** settings.
2.  Set **"Local echo"** to **"Force off"**.
3.  Set **"Local line editing"** to **"Force off"**.

### 4.2. TeraTerm

1.  Navigate to **Setup** -> **Terminal**.
2.  Ensure the **"Local echo"** checkbox is **unchecked**.

### 4.3. MobaXterm

MobaXterm typically handles this correctly by default in SSH sessions. If a double echo is observed, check the session settings to ensure "Local echo" is disabled.
