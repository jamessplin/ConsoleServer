# client_rfc2217.py Design Specification

## Overview
`client_rfc2217.py` is an advanced serial console client designed to connect to serial ports exposed by ser2net using the RFC2217 protocol. It supports both direct (simple) connections and connections with a control plane for session management and access control. The client is implemented in Python 3 using asyncio for asynchronous I/O.

## Key Features
- **RFC2217 Protocol Support:**
  - Full implementation of RFC2217 (COM Port Control) over telnet, including negotiation, break signals, and control line manipulation (DTR, RTS).
  - Handles telnet IAC (Interpret As Command) sequences and subnegotiations.
- **Flexible Connection Modes:**
  - **Simple Mode:** Direct connection to ser2net for quick access or testing (`--simple`).
  - **Control Plane Mode:** Connects to a separate control plane (e.g., seriald) for authentication, role management (writer/observer), and session tracking.
- **Escape Sequences:**
  - Interactive escape commands (Ctrl-]) for quitting, sending break, toggling DTR/RTS, and help.
- **Async I/O:**
  - Uses asyncio for concurrent reading from serial port, stdin, and (optionally) the control plane.
- **Configurable Parameters:**
  - Host, port, line number, baud rate, and control plane details are all configurable via command-line arguments.

## Architecture

### 1. RFC2217Client Class
- Encapsulates all RFC2217 protocol logic:
  - Telnet option negotiation (BINARY, SGA, COM_PORT_OPTION)
  - Sending/receiving data, handling IAC escapes
  - Subnegotiation for control signals and line parameters
  - Methods for sending break, setting DTR/RTS, baud rate, etc.

### 2. Connection Modes
- **Simple Mode (`--simple`):**
  - Connects directly to ser2net (host/port)
  - No authentication or session management
  - Suitable for local testing or when access control is handled externally
- **Control Plane Mode (default):**
  - Connects to a control plane server (host/port)
  - Authenticates and requests attach as writer/observer
  - Receives role changes and detach notifications
  - After authorization, connects to ser2net for data

### 3. Async Tasks
- **Serial Data Reader:** Reads from the serial port and writes to stdout.
- **Stdin Reader:** Reads from stdin, handles escape sequences, and sends data to the serial port (if writer).
- **Control Plane Reader (if used):** Handles role changes and detach events from the control plane.

### 4. User Interaction
- **Escape Mode:**
  - Entered via Ctrl-]
  - Commands: q (quit), b (break), d (toggle DTR), r (toggle RTS), ? (help)
- **Role Handling:**
  - Writer: Can send data to the serial port
  - Observer: Read-only access

## Command-Line Arguments
- `--host`: ser2net host (default: 127.0.0.1)
- `--port`: ser2net port (default: 20001)
- `--line`: Serial line number (default: 1)
- `--control-host`: Control plane host (default: 127.0.0.1)
- `--control-port`: Control plane port (default: 25001)
- `--observer`: Attach as observer (read-only)
- `--simple`: Use simple mode (no control plane)

## Example Usage
```
# Simple direct connection to ser2net
python3 client_rfc2217.py --simple --host 192.168.1.100 --port 20001

# With control plane
python3 client_rfc2217.py --host 192.168.1.100 --port 20001 \
  --control-host 192.168.1.100 --control-port 25001
```

## Extensibility
- The design allows for easy extension to support additional RFC2217 features or custom control plane protocols.
- The protocol handler is modular and can be reused in other serial-over-network applications.

## Limitations
- Only basic RFC2217 features are implemented; advanced flow control and error handling may require further development.
- The client assumes a UNIX-like environment for terminal I/O.

## Summary
`client_rfc2217.py` provides a robust, flexible, and extensible client for interacting with serial ports over the network using RFC2217, supporting both direct and managed (control plane) access modes, with a focus on interactive use and protocol correctness.

## Appendix: Test SOP (Standard Operating Procedure)

### 1. Prerequisites
- Ensure ser2net is installed and configured on the target host with RFC2217 support.
- Confirm the serial device (e.g., /dev/ttyUSB0) is connected and accessible.
- Confirm Python 3 is available on the client machine.

### 2. Configure ser2net
- Edit /etc/ser2net.yaml (or equivalent) to include an RFC2217 connection, e.g.:
  ```yaml
  connection: &line1
    accepter: telnet(rfc2217),20001
    connector: serialdev,/dev/ttyUSB0,115200n81,local
    options:
      kickolduser: true
  ```
- Restart ser2net:
  ```bash
  sudo systemctl restart ser2net
  ```

### 3. Verify ser2net is Listening
- On the ser2net host, check:
  ```bash
  ss -lntp | grep 20001
  ```
- You should see ser2net listening on the specified port.

### 4. Test Simple Direct Connection
- On the client machine, run:
  ```bash
  python3 client_rfc2217.py --simple --host <ser2net_host> --port 20001
  ```
- Replace `<ser2net_host>` with the IP or hostname of the ser2net server.
- Interact with the serial device. Use Ctrl-] for escape commands (q: quit, b: break, d: DTR, r: RTS, ?: help).

### 5. Test With Control Plane (if available)
- Ensure the control plane server (e.g., seriald) is running and accessible.
- Run:
  ```bash
  python3 client_rfc2217.py --host <ser2net_host> --port 20001 \
    --control-host <control_host> --control-port 25001
  ```
- Authenticate and verify role assignment (writer/observer).
- Test role changes and detach events from the control plane.

### 6. Functional Tests
- Send and receive data to/from the serial device.
- Use escape commands to send BREAK, toggle DTR/RTS, and quit.
- **Step 1:** Press `Ctrl-]` to enter escape mode. You should see a prompt or message indicating escape mode is active.
- **Step 2:**
    - Press `q` to quit the client. The session should close cleanly.
    - Press `b` to send a BREAK signal to the serial device. Observe the device's response (e.g., it may enter a bootloader or reset, depending on hardware).
    - Press `d` to toggle the DTR (Data Terminal Ready) signal. The client should display the new DTR state (ON/OFF). If your device responds to DTR, verify the behavior.
    - Press `r` to toggle the RTS (Request To Send) signal. The client should display the new RTS state (ON/OFF). If your device responds to RTS, verify the behavior.
    - Press `?` to display help for escape commands. Confirm the help text is shown.
- **Step 3:** After each escape command, the client should return to normal mode, allowing you to continue sending/receiving data.
- **Step 4:** For observer role, verify that typing does not send data to the serial port, but you can still receive data and use escape commands to quit or get help.
- **Step 5:** Repeat the above for both simple and control plane modes to ensure consistent behavior.

### 7. Troubleshooting
- If connection fails, check network/firewall settings and ser2net status.
- If no data is received, verify serial device connectivity and permissions.
- Use verbose/debug output if available for further diagnosis.

### 8. Cleanup
- Exit the client cleanly using escape commands.
- Restore any modified configuration files if needed.
