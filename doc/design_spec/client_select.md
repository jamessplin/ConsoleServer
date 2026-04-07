# Using `select` for a Non-Blocking `stdin` Reader

This document explains the rationale and implementation details behind the change to use `select.select()` in `client.py` for handling standard input.

## The Problem: Client Hanging on Disconnect

The previous version of `client.py` suffered from a critical bug: when the connection was terminated by the server (e.g., due to an inactivity timeout), the client process would hang for over 5 minutes before exiting.

The root cause was the `stdin_reader` task. This task was responsible for reading user input from the terminal. To avoid blocking the main `asyncio` event loop, the blocking call `sys.stdin.read(1)` was run in a separate thread using `loop.run_in_executor()`.

However, this created a new problem. When the server disconnected, the main `asyncio` loop would try to shut down all tasks. But the thread running `sys.stdin.read(1)` was stuck, waiting indefinitely for a character to be typed. The `asyncio` event loop could not fully exit until all executor threads had completed, leading to the long, noticeable hang.

## The Solution: Non-Blocking `select`

To fix this, the `stdin_reader` was re-implemented to be non-blocking and responsive to shutdown signals.

The solution involves these key components:

1.  **`select.select()` with a Timeout**: Instead of a blocking `read()`, the background thread now uses `select.select([sys.stdin], [], [], 0.1)`. This call monitors `sys.stdin` but times out after a short interval (0.1 seconds) if no input is available. This prevents the thread from ever getting stuck.

2.  **A Shared `done_event`**: A shared `asyncio.Event` is passed to all major tasks, including the `stdin_reader`. When a shutdown is initiated (e.g., by the server closing the connection), this event is set.

3.  **The `read_stdin_thread` Loop**: The background thread's main loop now does two things:
    *   It calls `select.select()` to check for input.
    *   It checks if `done_event.is_set()`.

Because the `select` call has a very short timeout, the thread is guaranteed to check the `done_event` frequently. As soon as the event is set, the thread sees the signal, breaks its loop, and terminates cleanly.

4.  **`asyncio.Queue`**: An `asyncio.Queue` is used as a thread-safe communication channel to pass characters read by the background thread back to the main `asyncio` event loop for processing.

### How it Works Together

1.  The main `bridge` function creates a `done_event`.
2.  The `control_plane_handler` detects a server disconnect and calls `done_event.set()`.
3.  The `read_stdin_thread`, which is polling in the background, sees that the `done_event` is set during its next check (within 0.1 seconds).
4.  The thread exits its loop and terminates.
5.  Because the thread has finished, the `run_in_executor` task completes.
6.  The main `asyncio` loop, which was waiting for all tasks to finish, can now proceed with a clean and immediate shutdown.

This new architecture ensures that the client is always responsive and can shut down gracefully under all conditions, completely resolving the hanging issue.
