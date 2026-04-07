# Serial Console Client Design Spec

## Overview
This document describes the design of the serial console client, which provides secure, authenticated access to serial devices over the network. The architecture separates the control plane (authentication, session management) from the data plane (serial data transport), leveraging ser2net for efficient serial port access.

## Architecture Diagram

```
+-------------------+        Control Plane         +-------------------+
|                   | <-------------------------> |                   |
|   Console Client  |                             |   Console Server  |
|  (client.py)      |                             |  (auth/session)   |
|                   |                             |                   |
+-------------------+                             +-------------------+
        |
        |  Data Plane (Telnet)
        v
+-------------------+                             +-------------------+
|                   |                             |                   |
|   ser2net         | <------ Serial Data ------> |  Serial Device(s) |
|  (telnet server)  |                             |  (/dev/ttyUSB*)   |
+-------------------+                             +-------------------+
```

## Components

### 1. Console Client (client.py)
- Handles user authentication and session control via the control plane.
- After successful login, establishes a telnet connection to ser2net for serial data transport.
- Forwards user input/output between the terminal and the serial device.

### 2. Console Server
- Authenticates users and manages session state.
- Authorizes access to specific serial lines.
- Instructs the client which ser2net port to use for the data plane.

### 3. ser2net
- Listens on configured telnet ports (e.g., 20001, 20002).
- Bridges each telnet port to a specific serial device (e.g., /dev/ttyUSB0).
- Handles low-level serial options (baud rate, parity, etc.) and session management (kickolduser, banners).

### 4. Serial Devices
- Physical serial ports (e.g., /dev/ttyUSB0, /dev/ttyUSB1) connected to target hardware.

## Data Flow
1. User launches the console client and authenticates via the control plane.
2. Upon successful authentication, the server provides the client with the correct ser2net port for the requested serial device.
3. The client establishes a telnet connection to ser2net on the specified port.
4. All serial data is proxied between the user's terminal and the serial device via ser2net.

## Example ser2net.yaml
```yaml
define: &banner \r\nser2net port \p device \d [\B] (Debian GNU/Linux)\r\n\r\n
connection: &com1
  accepter: tcp,20001
  enable: on
  connector: serialdev,/dev/ttyUSB0,115200n81,local
  options:
    kickolduser: true

connection: &com2
  accepter: tcp,localhost,20002
  enable: on
  options:
    banner: *banner
    kickolduser: true
    telnet-brk-on-sync: true
  connector: serialdev,
            /dev/ttyUSB1,
            57600n81,local
```

## Notes
- The control plane and data plane are logically separated for security and flexibility.
- ser2net handles only the data path; all authentication and authorization are managed by the console server.
- The client can be extended to support additional features (e.g., logging, auditing, multi-user coordination).

---
