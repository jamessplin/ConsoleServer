# seriald-client Design Specification (v3)

## Overview
This document describes the design and implementation of the unified, self-contained seriald-client for serial console access via RFC2217 (ser2net) and fakeserial backends. The client is intended for system-wide and embedded deployment, supporting robust RBAC, SSH/ForceCommand integration, and single-file install.

## Goals
- **Single-file deployment:** All protocol logic (RFC2217, backend abstraction) inlined; no external Python module dependencies.
- **Backend abstraction:** Supports RFC2217 (ser2net) and fakeserial (mock/testing) backends via a unified async interface.
- **RBAC enforcement:** User access controlled via seriald server/config.json.
- **SSH/ForceCommand compatibility:** Designed for use as a system-wide binary, invoked via SSH.
- **Escape/break handling:** Robust escape sequence support for BREAK, DTR/RTS toggling, and session control.

## Architecture
### Main Components
- **SerialBackend (abstract):** Async interface for serial operations (open, close, read, write, break, DTR/RTS, baudrate, line params).
- **RFC2217Backend:** Implements SerialBackend using inlined RFC2217Client and Telnet protocol logic. Connects to ser2net RFC2217 port (20000+line).
- **FakeserialBackend:** Implements SerialBackend for mock/testing; loopback and break simulation.
- **Backend Selection:** Auto-selects RFC2217 for lines 1-24, fakeserial otherwise, or forced via env/CLI.
- **Control Plane:** Connects to seriald server (default port 25001) for session management, RBAC, and data relay.
- **Session Management:** Handles attach/detach, role changes, override requests, and error reporting.
- **Escape Sequences:** '~b' for BREAK, 'exit' to detach, 'override' to request writer role.

### Protocols
- **RFC2217/Telnet:** All protocol constants, enums, and negotiation logic inlined. Handles option negotiation, subnegotiation, and data transfer.
- **Base64 Data Relay:** Data to/from server is base64-encoded for safe transport.

## Usage
- **CLI Arguments:**
  - `--host`: seriald/ser2net host (default: 127.0.0.1)
  - `--port`: control plane port (default: 25001)
  - `--line`: serial line number
  - `--observer`: attach as observer (read-only)
  - `--backend`: force backend (rfc2217/fakeserial)
- **Environment Variables:**
  - `SERIAL_BACKEND`: force backend selection
  - `SSH_USER`, `LOGNAME`, `USER`: used for session tracking

## Control Flow
1. **Startup:** Parse CLI args, select backend, connect to control plane.
2. **Backend Open:** RFC2217Backend connects to RFC2217 port, negotiates Telnet options; FakeserialBackend initializes mock queue.
3. **Session Attach:** Authenticate with control plane, await attach/role assignment.
4. **Data Relay:**
   - stdin → backend.write() → server
   - server → backend.write() (serial) or write_stdout() (echo)
   - backend.read() → write_stdout()
5. **Escape Handling:**
   - 'exit' → detach
   - 'override' → request writer
   - '~b' → send BREAK
6. **Session End:** On detach, disconnect, or error, exit cleanly.

## Error Handling
- All network/protocol errors are caught and reported to the user.
- Connection resets, RBAC denials, and server disconnects are handled gracefully.

## Deployment
- Install as `/usr/local/bin/seriald-client` for system-wide use.
- No external Python dependencies required.
- Compatible with SSH/ForceCommand and embedded/SONiC-style systems.

## Extensibility
- Additional backends can be added by implementing SerialBackend.
- Escape sequence handling is extensible for more commands.

## Security
- RBAC enforced via seriald server/config.json.
- User identity tracked via environment and getpass.

## References
- RFC2217: Telnet Com Port Control Option
- ser2net: https://ser2net.sourceforge.net/
- Python asyncio documentation

---
Design spec generated for seriald-client v3, reflecting current codebase and deployment model.
