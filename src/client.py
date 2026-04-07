#!/usr/bin/env python3
import asyncio
import base64
import json
import os
import sys
import getpass
import tty
import termios
import time
import select

# Telnet command constants
IAC  = b'\xff'  # Interpret as Command
DONT = b'\xfe'
DO   = b'\xfd'
WONT = b'\xfc'
WILL = b'\xfb'
ECHO = b'\x01'  # Echo option
SGA  = b'\x03'  # Suppress Go Ahead option

# The old backend classes are no longer needed.
# The client will manage a raw TCP socket for the data plane
# and a control connection to the seriald server.

def write_stdout(data: bytes):
    """Safely write bytes to stdout."""
    try:
        os.write(sys.stdout.fileno(), data)
    except OSError:
        pass

def setup_raw_terminal():
    """Configure the terminal for raw mode."""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return None
    old_attrs = termios.tcgetattr(fd)
    tty.setraw(fd)
    return old_attrs

def restore_terminal(old_attrs):
    """Restore terminal to its original settings."""
    if old_attrs:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_attrs)

async def bridge(host: str, port: int, line: int, want_writer: bool):
    """Main function to bridge stdin/stdout to the seriald control and data planes."""
    # Event to signal successful attachment
    attach_event = asyncio.Event()
    # Event to signal that the connection is finished
    done_event = asyncio.Event()
    # Dictionary to hold the role and other details from the server
    role_holder = {
        "role": None,
        "mode": "exclusive",
        "fakeserial": False,
        "ser2net_host": None,
        "ser2net_port": None,
    }

    # Control plane connection (seriald)
    try:
        ctl_reader, ctl_writer = await asyncio.open_connection(host, port)
    except Exception as e:
        write_stdout(f"\r\n[Error] Cannot connect to seriald at {host}:{port}: {e}\r\n".encode())
        return

    # Data plane connection (ser2net or fakeserial)
    data_reader, data_writer = None, None

    # Get user info and send attach message
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"

    attach_msg = {
        "op": "attach",
        "line": line,
        "mode": "writer" if want_writer else "observer",
        "user": user,
        "client_ip": os.environ.get("SSH_CLIENT_IP"),
        "client_port": os.environ.get("SSH_CLIENT_PORT"),
    }
    ctl_writer.write(json.dumps(attach_msg).encode() + b"\n")
    await ctl_writer.drain()
    write_stdout(b"\r\n[Connecting to seriald...]\r\n")

    original_termios = None
    pending_tasks = set()

    try:
        # Set up a single, dedicated task for reading from the control plane.
        # This task will handle the initial attach response and all subsequent messages.
        control_task = asyncio.create_task(
            control_plane_handler(ctl_reader, ctl_writer, attach_event, role_holder, done_event)
        )
        pending_tasks.add(control_task)

        # Wait for the attach to complete. The control_plane_handler will signal
        # this by setting the attach_event.
        await asyncio.wait_for(attach_event.wait(), timeout=10.0)

        # Check if attach was successful
        if role_holder["role"] is None:
            # The control_task has already printed a specific error and exited.
            # Awaiting the completed task allows us to observe its result (e.g., re-raise any unexpected exceptions) before we exit.
            await control_task
            return

        role = role_holder["role"]
        mode = role_holder["mode"]
        is_fakeserial = role_holder["fakeserial"]
        ser2net_host = role_holder["ser2net_host"]
        ser2net_port = role_holder["ser2net_port"]

        write_stdout(f"[Attached to line {line} as {role} in {mode} mode]\r\n".encode())
        write_stdout(b"Tip: Press ~. to detach.\r\n")

        # Now that we are attached, set terminal to raw mode
        original_termios = setup_raw_terminal()

        if not is_fakeserial and ser2net_host and ser2net_port:
            try:
                write_stdout(f"[Connecting to data plane at {ser2net_host}:{ser2net_port}...]\r\n".encode())
                data_reader, data_writer = await asyncio.open_connection(ser2net_host, ser2net_port)

                # Perform Telnet negotiation to prevent garbage characters
                await telnet_negotiate(data_reader, data_writer)

                pending_tasks.add(asyncio.create_task(data_plane_reader(data_reader, done_event)))
            except Exception as e:
                write_stdout(f"\r\n[Error] Cannot connect to data plane: {e}\r\n".encode())
                done_event.set() # Signal all other tasks to stop

        # Start stdin reader only if we have a valid connection
        if not done_event.is_set():
            stdin_task = asyncio.create_task(stdin_reader(ctl_writer, data_writer, role_holder, mode, is_fakeserial, done_event))
            pending_tasks.add(stdin_task)

        # Wait for any task to complete.
        # The control_plane_handler sets done_event on disconnect, which causes
        # other tasks to finish gracefully.
        if pending_tasks:
            done, pending = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            # Propagate exceptions from the completed task
            for task in done:
                if task.exception():
                    # This will be caught by the outer try/except block
                    raise task.exception()

    except asyncio.TimeoutError:
        write_stdout(b"\r\n[Connection timed out during attach]\r\n")
    except KeyboardInterrupt:
        write_stdout(b"\r\n[Detaching...]\r\n")
    except Exception as e:
        # This will catch errors from tasks as well as connection errors
        if not isinstance(e, (ConnectionResetError, asyncio.CancelledError)):
             write_stdout(f"\r\n[An unexpected error occurred: {e}]\r\n".encode())
    finally:
        # Ensure the done event is set to signal all tasks to exit
        done_event.set()

        # Cancel all still-running tasks
        # Create a copy as the set might change during iteration
        current_tasks = list(pending_tasks)
        for task in current_tasks:
            if not task.done():
                task.cancel()
        # Wait for all tasks to acknowledge cancellation
        if current_tasks:
            await asyncio.gather(*current_tasks, return_exceptions=True)

        if original_termios:
            restore_terminal(original_termios)
        # Close writers and wait for them to be fully closed
        for writer in [ctl_writer, data_writer]:
            if writer and not writer.is_closing():
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass # Ignore errors on close
        write_stdout(b"[Disconnected]\r\n")


async def control_plane_handler(reader, writer, attach_event, role_holder, done_event):
    """
    Handles all messages from the seriald server.
    This single task is responsible for the entire lifecycle of the control connection.
    """
    try:
        # 1. Handle the initial attach response
        attach_response = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not attach_response:
            write_stdout(b"\r\n[Error] Did not receive attach response from server.\r\n")
            return

        msg = json.loads(attach_response.decode())
        if msg.get("op") != "attach" or not msg.get("ok"):
            err_msg = msg.get("msg", "Attach failed")
            write_stdout(f"\r\n[Error] {err_msg}\r\n".encode())
            # Do not set attach_event, let the main loop time out or handle the None role
            return

        # Successfully attached, store details and signal event
        role_holder["role"] = msg.get("role", "observer")
        role_holder["mode"] = msg.get("mode", "exclusive")
        role_holder["fakeserial"] = msg.get("fakeserial", False)
        role_holder["ser2net_host"] = msg.get("ser2net_host")
        role_holder["ser2net_port"] = msg.get("ser2net_port")
        attach_event.set()

        # 2. Process subsequent messages from the server
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line.decode())
            op = msg.get("op")

            if op == "echo":
                data = base64.b64decode(msg.get("data", ""))
                write_stdout(data)
            elif op == "role":
                new_role = msg.get("role", "observer")
                role_holder["role"] = new_role
                write_stdout(f"\r\n[Role changed to {new_role}]\r\n".encode())
            elif op == "error":
                write_stdout(f"\r\n[Server Error] {msg.get('msg')}\r\n".encode())
            elif op == "detach":
                write_stdout(b"\r\n[Detached by server]\r\n")
                # Do not close the writer here, just signal done.
                # The main finally block will handle cleanup.
                break
    except (asyncio.TimeoutError, ConnectionResetError, json.JSONDecodeError, asyncio.CancelledError) as e:
        # Don't print an error if it's just a timeout on attach, main handles that.
        if not (isinstance(e, asyncio.TimeoutError) and not attach_event.is_set()):
            if not done_event.is_set(): # Avoid duplicate messages
                write_stdout(f"\r\n[Control connection lost: {type(e).__name__}]\r\n".encode())
    finally:
        # If the handler exits for any reason (e.g., timeout, error, disconnect),
        # ensure the main loop can unblock and all other tasks can exit cleanly.
        done_event.set()
        # Set the attach event anyway to unblock the main function if it's waiting
        if not attach_event.is_set():
            attach_event.set()


async def control_plane_reader(reader, writer, initial_msg=None):
    """Reads messages from the seriald server (echoes, roles, etc.)."""
    async def process_message(msg):
        op = msg.get("op")
        if op == "echo":
            data = base64.b64decode(msg.get("data", ""))
            write_stdout(data)
        elif op == "role":
            role = msg.get("role", "observer")
            write_stdout(f"\r\n[Role changed to {role}]\r\n".encode())
        elif op == "error":
            write_stdout(f"\r\n[Server Error] {msg.get('msg')}\r\n".encode())
        elif op == "detach":
            write_stdout(b"\r\n[Detached by server]\r\n")
            # This will cause the main loop to exit
            writer.close()

    if initial_msg:
        await process_message(initial_msg)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line.decode())
            await process_message(msg)
        except (ConnectionResetError, json.JSONDecodeError):
            break

async def data_plane_reader(reader, done_event):
    """Reads from the ser2net data plane and writes to stdout."""
    while not done_event.is_set():
        try:
            # Wait for data with a timeout, so we can check done_event
            data = await asyncio.wait_for(reader.read(4096), timeout=0.1)
            if not data:
                # Connection closed by peer
                write_stdout(b"\r\n[Data plane connection closed]\r\n")
                break
            write_stdout(data)
        except asyncio.TimeoutError:
            # No data, loop again to check done_event
            continue
        except (ConnectionResetError, asyncio.CancelledError):
            break
    # Signal other tasks to exit
    done_event.set()

async def stdin_reader(ctl_writer, data_writer, role_holder, mode, is_fakeserial, done_event):
    """Reads from stdin (raw) and forwards to the correct writer, handling escape sequences."""
    loop = asyncio.get_running_loop()
    char_queue = asyncio.Queue()

    def read_stdin_thread():
        """
        Runs in a separate thread, reading from stdin without blocking the event loop.
        Uses select() to be able to check the done_event periodically.
        """
        while not done_event.is_set():
            # Wait for stdin to be readable, with a short timeout
            readable, _, _ = select.select([sys.stdin], [], [], 0.1)
            if readable:
                try:
                    char = sys.stdin.read(1)
                    if not char:
                        break # EOF
                    # This is thread-safe
                    loop.call_soon_threadsafe(char_queue.put_nowait, char.encode())
                except (IOError, OSError):
                    break
        # Signal that we are done by putting None in the queue
        loop.call_soon_threadsafe(char_queue.put_nowait, None)

    # Start the stdin reader thread in the default executor
    stdin_thread_future = loop.run_in_executor(None, read_stdin_thread)

    at_line_start = True
    try:
        while not done_event.is_set():
            # Wait for a character from the queue, but with a timeout
            # so we can check the done_event.
            try:
                char_bytes = await asyncio.wait_for(char_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue

            if char_bytes is None: # End of stream from thread
                break

            # In exclusive mode, observers cannot type at all.
            if mode == "exclusive" and role_holder.get("role") == "observer":
                continue

            char_ord = char_bytes[0]

            # --- Escape Sequence Handling ---
            if at_line_start and char_ord == ord('~'):
                try:
                    # Wait for the next character to complete the sequence
                    next_char_bytes = await asyncio.wait_for(char_queue.get(), timeout=1.0)
                    if next_char_bytes is None: break

                    next_char = next_char_bytes[0]
                    if next_char == ord('.'): # ~. to disconnect
                        write_stdout(b"\r\n[Disconnecting by escape sequence ~.]\r\n")
                        raise KeyboardInterrupt
                    elif next_char in (ord('b'), ord('B')): # ~b to send BREAK
                        if role_holder.get("role") == "writer" and data_writer:
                            # Telnet IAC BREAK sequence
                            break_sequence = IAC + b'\xf3'
                            data_writer.write(break_sequence)
                            await data_writer.drain()
                            write_stdout(b"\r\n[Sent BREAK to serial port]\r\n")
                        else:
                            write_stdout(b"\r\n[Must be writer to send BREAK]\r\n")
                        at_line_start = True # Reset for next line
                        continue
                    else:
                        # Not a valid escape sequence, send both characters
                        char_bytes += next_char_bytes
                except asyncio.TimeoutError:
                    # Only a tilde was typed, send it through
                    pass

            # Update line start state
            at_line_start = char_bytes.endswith(b'\r') or char_bytes.endswith(b'\n')

            # --- Data Forwarding ---
            if (mode == "shared") or (mode == "exclusive" and role_holder.get("role") == "writer"):
                # For real devices, input goes to the data plane
                if data_writer and not data_writer.is_closing():
                    data_writer.write(char_bytes)
                    await data_writer.drain()

                # For fakeserial, input goes to the control plane
                elif is_fakeserial and not ctl_writer.is_closing():
                    msg = {
                        "op": "input",
                        "data": base64.b64encode(char_bytes).decode()
                    }
                    ctl_writer.write(json.dumps(msg).encode() + b"\n")
                    await ctl_writer.drain()

    except (IOError, ConnectionResetError, asyncio.CancelledError):
        pass # These are expected on exit
    except KeyboardInterrupt:
        # Propagate to main loop for cleanup
        raise
    finally:
        # Ensure the reader thread can exit and wait for it to finish
        done_event.set()
        if 'stdin_thread_future' in locals() and not stdin_thread_future.done():
             await stdin_thread_future

async def telnet_negotiate(reader, writer):
    """
    Performs a more robust Telnet negotiation.
    This version actively responds to server commands (DO/WILL)
    with appropriate refusals (WONT/DONT) to ensure no negotiation
    bytes are passed to the underlying shell as data.
    """
    # Give the server a moment to send its initial commands
    await asyncio.sleep(0.1)

    # Read and process commands from the server for a short period.
    # This is more reliable than sending unsolicited WONTs.
    start_time = time.time()
    while time.time() - start_time < 0.5: # Negotiation window
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=0.1)
            if not data:
                break

            response = b''
            i = 0
            while i < len(data):
                if data[i:i+1] == IAC:
                    command = data[i+1:i+2]
                    option = data[i+2:i+3]

                    # Server asks us to DO something (e.g., ECHO). We refuse with WONT.
                    if command == DO:
                        response += IAC + WONT + option
                    # Server says it WILL do something. We refuse with DONT.
                    elif command == WILL:
                        response += IAC + DONT + option
                    # We ignore all other commands (e.g. SB/SE)

                    i += 3 # Move past the 3-byte command
                else:
                    # This is unexpected data during negotiation. Pass it through.
                    # It might be a banner that was sent before negotiation.
                    # We look for IAC to resync.
                    next_iac = data.find(IAC, i)
                    if next_iac == -1:
                        # No more IACs, the rest is data
                        i = len(data)
                    else:
                        i = next_iac

            if response:
                writer.write(response)
                await writer.drain()

        except asyncio.TimeoutError:
            # No more data from server, negotiation is likely complete
            break
        except (ConnectionResetError, IndexError):
            break

    # Final check: Politely refuse to echo and suppress go-ahead, just in case.
    # This reinforces our desired state.
    writer.write(IAC + WONT + ECHO)
    writer.write(IAC + WONT + SGA)
    await writer.drain()

async def main():
    import argparse
    p = argparse.ArgumentParser(description="Client for seriald")
    p.add_argument("--host", default="127.0.0.1", help="seriald server host")
    p.add_argument("--port", type=int, default=25001, help="seriald server port")
    p.add_argument("--line", type=int, required=True, help="serial line to attach to")
    p.add_argument("--observer", action="store_true", help="attach as observer (read-only)")
    args = p.parse_args()

    await bridge(args.host, args.port, args.line, want_writer=not args.observer)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        write_stdout(b"\r\n") # Move to a new line after ~. exit
        pass