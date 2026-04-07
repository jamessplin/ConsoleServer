# seriald Server Design Spec

This document describes the design of the asyncio-based serial daemon implemented in [tools/seriald/server.py](tools/seriald/server.py). The daemon centralizes access to one or more serial lines, arbitrates writer roles (exclusive or coordinated shared), and broadcasts device output to all attached clients.

## Overview

- Purpose: Provide a single, shared process that fronts real or simulated serial devices, coordinating multiple SSH-launched clients attached per line.
- Modes: Per-line `exclusive` (one writer; observers see output) and `shared` (cooperative write windows via micro-lock).
- Client Limit: Each line can specify a maximum number of clients (`max_clients`) in the config. This limits the total number of clients (writer + observers) that can attach to a line. If set to 1, the line operates in single-user mode (only one client allowed). If the client limit is reached, new attaches are rejected with an error. If null or false, the number of clients is unbounded.
- Backends: Fake serial device for demo, and real serial via PySerial (local `/dev/tty*` or RFC2217 `rfc2217://host:port`).
- Transport: Clients connect over TCP to the daemon, speak a JSON line protocol, and receive device output and role updates.
- Keepalive: Periodic lightweight pings prune broken client connections and repair line state.

## Architecture

- **Core Class: `SerialDaemon`**
  - Tracks per-line configuration, client sets, `active_writer`, observer queues, shared-mode micro-locks, and backend instances.
  - Spawns per-line serial RX tasks and a global keepalive task.
- **Data Model: `Client`**
  - Holds the client connection (`asyncio.StreamWriter`), current `line_id`, `can_write` flag, and `user` identifier.
- **Backends**
  - `FakeSerialDevice`: simple state machine that simulates login and a shell, used for demo.
  - `PySerialBackend`: wraps `pyserial.serial_for_url` to support local devices and RFC2217; runs a polling RX thread and queues reads back to the daemon.
- **Concurrency**
  - Async TCP server via `asyncio.start_server` with per-connection coroutine `handle_client()`.
  - Per-line RX loop tasks push device output to all attached clients.
  - Keepalive task periodically sends `ping` and cleans up broken connections.

## Configuration

- Source: JSON file provided to `server.py --config`, or defaults if omitted.
- Shape:
  ```json
  {
    "listen": {"host": "127.0.0.1", "port": 25001},
    "lines": {
            "1": {"mode": "exclusive", "echo": true, "window_ms": 800, "max_clients": 3},
            "2": {"mode": "shared",    "echo": true, "window_ms": 800, "max_clients": 4,
              "device": "/dev/ttyS0", "baud": 115200}
    },
    "keepalive_ms": 15000
  }
  ```
- Fields:
  - `listen.host`/`listen.port`: daemon TCP bind address.
  - `lines[N].mode`: `exclusive` or `shared`.
  - `lines[N].echo`: when true, observers see writer keystrokes.
  - `lines[N].window_ms`: shared-mode write window duration.
  - `lines[N].max_clients`: maximum number of clients (writer + observers) allowed for the line. If 1, only a single user is allowed (single-user mode). If the client limit is reached, new attaches are rejected with an error. If null or false, the number of clients is unbounded.
  - Backend fields for real devices: `device` or `url`, optional `baud`, `rtscts`, `dsrdtr`, `xonxoff`.
  - `keepalive_ms`: interval for pruning broken connections (min clamped to 5s).

## Wire Protocol (JSON per line, newline-delimited)

### Client → Server
- `attach`: request to attach to a line and desired role.
  - Example: `{ "op": "attach", "line": 1, "mode": "writer", "user": "bob" }`
- `input`: send device input data (base64-encoded bytes).
  - Example: `{ "op": "input", "data": "Ym9iXHBhc3N3b3JkXG4=" }`
- `override`: request to become writer (exclusive mode), demoting current writer.
  - Example: `{ "op": "override" }`
- `status`: request a snapshot of all lines, roles, and clients.
  - Example: `{ "op": "status" }`
- `detach`: gracefully detach from the current line.
  - Example: `{ "op": "detach" }`

### Server → Client
- `attach`: acknowledgement with assigned role.
  - `{ "op": "attach", "ok": true, "role": "writer" | "observer", "line": 1 }`
- `role`: role change notification (e.g., promotion).
  - `{ "op": "role", "role": "writer", "line": 1, "reason": "promote" }`
- `override`: result of override request.
  - `{ "op": "override", "ok": true }`
- `serial`: device output bytes (base64-encoded) broadcast to all attached clients.
  - `{ "op": "serial", "line": 1, "data": "..." }`
- `echo`: writer keystrokes echoed to observers when `echo` is enabled.
  - `{ "op": "echo", "line": 1, "data": "..." }`
- `error`: error message for invalid operations or data.
  - `{ "op": "error", "msg": "not writer" }`
- `detach`: confirmation of a detach operation.
  - `{ "op": "detach", "ok": true }`
- `ping`: periodic keepalive to detect broken connections.
  - `{ "op": "ping", "line": 1, "ts": 1737062800.123 }`
- `status`: snapshot across lines, writer, counts, and client list.
  - `{ "op": "status", "lines": [ { "line": 1, "mode": "exclusive", "writer": "bob", "counts": {"clients": 2, "writers": 1, "observers": 1}, "clients": [ {"user": "bob", "role": "writer"}, {"user": "alice", "role": "observer"} ] } ] }`

## Role Arbitration

- **Exclusive Mode**
  - Single `active_writer` per line. First attaching client that requests `writer` becomes writer if none exists; others are observers.
  - Observers join a per-line FIFO queue (limited by max_clients in exclusive mode). When the writer detaches or drops, the daemon promotes the oldest observer to writer and notifies them via `role`.
  - `override` sets the requester as writer, demotes the previous writer, and places the demoted writer at the front of the queue.
- **Shared Mode**
  - All clients can attempt writes, gated by a micro-lock per line: `line_lock = { client, deadline }`.
  - Lock acquisition: first writer creates the lock with deadline `now + window_ms/1000`.
  - Other writers receive `error: busy` while locked.
  - Lock release: on newline (`\n` or `\r`) or when the deadline passes.
  - Echo behavior mirrors exclusive mode when enabled.

## Backend Details

- **FakeSerialDevice**
  - Simulates a device boot, login (`login:` → `Password:`), basic credentials (`admin/password` or `bob/bob`), and a simple shell. Supports `exit/logout` to return to login.
  - RX/TX implemented via Python `queue.Queue` and a background thread.
- **PySerialBackend**
  - Uses `serial_for_url` to open `device` or RFC2217 `url`.
  - RX thread polls `in_waiting`; falls back to small reads and sleeps; enqueues data to `rx` queue.

## Keepalive and Cleanup

- Keepalive loop sends `ping` at `keepalive_interval`. Failed sends or drains mark clients as broken and remove them from line sets and observer queues.
- When the last client detaches from a line, the daemon clears `active_writer`, `line_lock`, and the observer queue to avoid stale state.
- On writer disconnect, the daemon schedules promotion of the next observer if in exclusive mode.

## Error Handling

- Invalid JSON: `error: invalid json`.
- Bad input data (base64): `error: bad data`.
- Not attached: `error: not attached`.
- Not writer (exclusive): `error: not writer`.
- Busy (shared lock held by other client): `error: busy`.
- Unknown op: `error: unknown op`.

## Server Startup and Lifecycle

- Entrypoint: `asyncio.run(main(host, port, config_path))` in [tools/seriald/server.py](tools/seriald/server.py).
- Config load: reads JSON file, applies defaults, and builds `SerialDaemon`.
- TCP bind: `asyncio.start_server(d.handle_client, host, port)`; prints listen addresses; serves forever.
- Tasks: Per-line RX tasks created on first attach; keepalive task started on server startup.

## Status Reporting

- `status` op assembles per-line entries including:
  - `mode`: `exclusive` or `shared` by line config.
  - `writer`: current writer username (if any).
  - `counts`: `{ clients, writers, observers }`.
  - `clients`: list of attached clients and their current roles.

## Performance Notes

- Shared-mode micro-lock uses `window_ms` to bound contention; tune based on device echo latency and typical command lengths.
- PySerial RX thread relies on polling (`in_waiting` + small reads); adjust sleep intervals for device throughput.
- Echo broadcasts incur per-client JSON encoding and drain; number of observers affects CPU usage.

## Extensibility

- Hooks to integrate authentication/authorization or policy:
  - Replace or extend exclusive-mode policy for writer assignment.
  - Add per-line ACLs or rate limits.
- Additional operations could include named sessions, reconnect tokens, or per-line attributes (e.g., flow control changes).
- Backend abstraction allows adding other transports (e.g., TCP proxies, telnet-like backends).

## Integration

- Intended to be launched via SSH `ForceCommand` wrappers so users attach directly to lines by port selection or tokenized commands.
- See [tools/seriald/README.md](tools/seriald/README.md) for SSH integration examples and client usage.

## Testing & Verification

- Start daemon: `python3 tools/seriald/server.py --config tools/seriald/config.json`.
- Attach clients: `python3 tools/seriald/client.py --line 1` and `--observer`.
- Exercise exclusive promotions: detach writer; confirm observer promotion via `[Promoted to writer]`.
- Check status: `python3 tools/seriald/status.py` or `seriald-status` when installed.
