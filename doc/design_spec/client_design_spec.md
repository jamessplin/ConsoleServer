
# Seriald Client Design Specification

## 1. Purpose
The `seriald` client is a command-line tool that connects to a `seriald` server to provide interactive access to serial console lines over a network. It establishes a primary **control plane** connection to `seriald` for managing the session and a secondary **data plane** connection (usually to a `ser2net` instance) for the raw serial data stream.

It is designed to be robust, handling unexpected disconnects gracefully and ensuring the user's terminal is always restored to a usable state.

## 2. Requirements
- Connect to a `seriald` server via a TCP/IP control plane.
- Connect to a `ser2net` data plane for raw serial I/O.
- Perform Telnet negotiation on the data plane to ensure a clean data stream.
- Support two roles: **writer** (can send input) and **observer** (read-only).
- Provide a simple CLI interface for specifying host, port, line, and role.
- Handle server messages for attach, detach, role changes, and errors.
- Handle user input via a non-blocking mechanism to prevent the client from hanging.
- Support local escape sequences: `~.` (detach) and `~b` (send BREAK). `Ctrl+C` also detaches.
- Use `asyncio` for concurrent handling of network I/O and user input.
- Ensure graceful shutdown on any connection loss, error, or user-initiated exit.
- Restore the user's terminal to its original state on exit.

## 3. Architecture
The client operates on a multi-tasking, event-driven architecture using Python's `asyncio` library. The core design revolves around a main `bridge` function that orchestrates several concurrent tasks.

### Key Architectural Concepts
- **Control/Data Plane Split**: The connection is split into two distinct planes:
    1.  **Control Plane**: A JSON-based message channel to the `seriald` server for session management (attach, detach, role changes). Handled by `control_plane_handler`.
    2.  **Data Plane**: A raw TCP stream to the `ser2net` port for serial data. Handled by `data_plane_reader`.
- **Event-based Signaling**: The entire application lifecycle is managed by two `asyncio.Event` objects:
    1.  `attach_event`: Signals that the initial connection and handshake with the server are complete, allowing other tasks to proceed.
    2.  `done_event`: A global shutdown signal. When set, all concurrent tasks are notified that they should terminate cleanly.
- **Non-Blocking `stdin`**: To prevent the client from hanging while waiting for user input, the `stdin_reader` uses a background thread. This thread uses `select.select()` with a short timeout to poll for input, ensuring it never blocks indefinitely and can respond to the `done_event` shutdown signal.

### Session Flow Diagram

```mermaid
flowchart TD
    subgraph Initialization
        A[User starts client] --> B[bridge() starts]
        B --> C{Create attach_event, done_event}
        C --> D[Connect to seriald (Control Plane)]
        D --> E[Start control_plane_handler task]
        E --> F[Send attach request]
        F --> G[await attach_event.wait()]
    end

    subgraph "Control Plane Task"
        CP_H[control_plane_handler] -- Receives attach OK --> CP_I[Sets attach_event]
        CP_H -- Receives server message --> CP_J[Process echo, role, detach]
        CP_H -- Connection lost/error --> CP_K[Sets done_event]
    end

    subgraph "Main Flow (Post-Attach)"
        G -- Event set --> H[Attach successful]
        H --> I[Connect to ser2net (Data Plane)]
        I --> J[Start data_plane_reader task]
        H --> K[Start stdin_reader task]
    end

    subgraph "Concurrent Tasks"
        J -- Reads serial data --> L[Writes to stdout]
        K -- Reads user input --> M[Writes to Data/Control Plane]
        J -- Connection lost --> N[Sets done_event]
        K -- User presses ~. or Ctrl+C --> O[Raises KeyboardInterrupt]
    end

    subgraph Shutdown
        P[Any task sets done_event] --> Q{Main loop unblocks}
        O --> Q
        Q --> R[finally block executes]
        R --> S[done_event.set() (guarantee)]
        S --> T[Cancel all pending tasks]
        T --> U[await asyncio.gather() to wait for cancellation]
        U --> V[Restore terminal settings & close connections]
        V --> W[Client exits]
    end
```

## 4. Main Functions
- `main()`: CLI entry point, argument parsing, starts the `asyncio` event loop.
- `bridge(host, port, line, want_writer)`: The main orchestrator. It establishes connections, creates and manages all `asyncio` tasks, and contains the primary `try...finally` block that ensures graceful cleanup.
- `control_plane_handler()`: Runs for the entire session. It handles the initial attach handshake and processes all subsequent JSON messages from the `seriald` server. It is the primary task responsible for setting the `done_event` on a server-initiated disconnect.
- `data_plane_reader()`: Reads raw data from the `ser2net` connection and writes it to `stdout`. It uses a short timeout to remain responsive to the `done_event`.
- `stdin_reader()`: Manages user input. It spawns a background thread that uses `select()` to read from `stdin` without blocking. It forwards input to the appropriate plane and handles local escape sequences.
- `telnet_negotiate()`: Performs the initial Telnet negotiation on the data plane to refuse options like ECHO and ensure a clean data stream.

## 5. Concurrency and Shutdown Model
The client's stability hinges on its robust shutdown mechanism.
1.  **Initiation**: A shutdown is initiated when any task exits, a critical error occurs, or the user presses `Ctrl+C`. The primary trigger is a connection loss, which causes a reader task to exit and set the `done_event`.
2.  **Signaling**: The `done_event` immediately notifies all other tasks that they should exit. Tasks are designed with short timeouts on I/O operations so they check this event frequently.
3.  **Fail-safe Cancellation**: The main `finally` block in `bridge` ensures termination. It first calls `done_event.set()` (as a safeguard), then iterates through all tasks and calls `task.cancel()`. This injects a `CancelledError` into any task that hasn't already exited, forcing it to stop.
4.  **Waiting**: `asyncio.gather()` is used to wait for all tasks to acknowledge cancellation and finish. This prevents the client from exiting before all resources are released.
5.  **Cleanup**: Finally, the terminal is restored to its original state and all network connections are closed.

## 6. Usage Example
```sh
# Attach to line 2 as a writer
./client.py --host 127.0.0.1 --port 25001 --line 2

# Attach as a read-only observer
./client.py --host 127.0.0.1 --port 25001 --line 2 --observer

# Inside the client:
# Press Ctrl+C to detach.
# At the beginning of a new line, type ~. to detach.
# At the beginning of a new line, type ~b to send a Telnet BREAK signal.
```

## 7. Error Handling
- **Attach Timeout**: If the server doesn't confirm the attach within 10 seconds, the client exits with a timeout message.
- **Attach Failure**: If the server rejects the attach (e.g., line busy), the specific error is printed and the client exits.
- **Connection Loss**: Loss of either the control or data plane connection triggers the full graceful shutdown sequence.
- **Task Exceptions**: Exceptions in background tasks are not ignored. They are propagated to the main `bridge` function and caught, triggering a graceful shutdown.

