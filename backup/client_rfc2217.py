#!/usr/bin/env python3
"""
Usage:
    python3 client_rfc2217.py --host <ser2net_host> --port <tcp_port> [options]

Example:
    python3 client_rfc2217.py --host 127.0.0.1 --port 20001


Examples:
    # Simple direct connection to ser2net
    python3 client_rfc2217.py --simple --host 192.168.1.100 --port 20001

    # With control plane
    python3 client_rfc2217.py --host 192.168.1.100 --port 20001 \
      --control-host 192.168.1.100 --control-port 25001

    # Default example
    python3 client_rfc2217.py --host 127.0.0.1 --port 20001

    Supports break signals, line parameter changes, and escape sequences.

Options:
    --host <host>      Hostname or IP address of the ser2net server (default: 127.0.0.1)
    --port <port>      TCP port exposed by ser2net (e.g., 20001)
    --baud <baudrate>  Set baud rate (optional)
    --help             Show this help message

Escape Sequences:
    Ctrl-]             Enter command mode (type 'help' for commands)
    ~B                 Send BREAK signal
    ~.                 Exit client
"""
"""
Enhanced Serial Console Client with RFC2217 Support

This client connects directly to ser2net using RFC2217 protocol instead of plain telnet.
RFC2217 (COM Port Control Protocol) extends telnet to support serial port control signals,
line parameters, and other serial-specific features.

Features:
- Direct socket connection to ser2net (RFC2217-compatible)
- Support for sending BREAK signals via RFC2217
- Support for serial port control (DTR, RTS)
- Support for line parameter negotiation (baud rate, data bits, parity, stop bits)
- Handling of IAC (Interpret As Command) sequences
- Escape sequences for user control
"""

import asyncio
import base64
import json
import os
import sys
import getpass
import struct
from enum import IntEnum
from typing import Optional, Tuple

# ============================================================================
# RFC2217 Constants and Protocol Definitions
# ============================================================================

# Telnet protocol constants
class TelnetCmd(IntEnum):
    """Telnet command codes"""
    SE = 240    # End of subnegotiation parameters
    NOP = 241   # No operation
    DM = 242    # Data mark
    BRK = 243   # Break
    IP = 244    # Interrupt process
    AO = 245    # Abort output
    AYT = 246   # Are you there
    EC = 247    # Erase character
    EL = 248    # Erase line
    GA = 249    # Go ahead
    SB = 250    # Subnegotiation begin
    WILL = 251  # Will
    WONT = 252  # Won't
    DO = 253    # Do
    DONT = 254  # Don't
    IAC = 255   # Interpret as command

class TelnetOption(IntEnum):
    """Telnet option codes"""
    BINARY = 0          # Binary transmission
    ECHO = 1            # Echo
    SGA = 3             # Suppress Go Ahead
    COM_PORT_OPTION = 44  # RFC2217 COM Port Control

class RFC2217Command(IntEnum):
    """RFC2217 COM Port Control commands"""
    SIGNATURE = 0
    SET_BAUDRATE = 1
    SET_DATASIZE = 2
    SET_PARITY = 3
    SET_STOPSIZE = 4
    SET_CONTROL = 5
    NOTIFY_LINESTATE = 6
    NOTIFY_MODEMSTATE = 7
    FLOWCONTROL_SUSPEND = 8
    FLOWCONTROL_RESUME = 9
    SET_LINESTATE_MASK = 10
    SET_MODEMSTATE_MASK = 11
    PURGE_DATA = 12

# RFC2217 Control Signal bits
class ControlSignal(IntEnum):
    """RFC2217 control signal bits"""
    DTR = 0x01
    RTS = 0x02
    CTS = 0x10
    DSR = 0x20
    RI = 0x40
    DCD = 0x80

# ============================================================================
# RFC2217 Protocol Handler
# ============================================================================

class RFC2217Client:
    """
    RFC2217 (COM Port Control) protocol handler.

    This class implements the RFC2217 protocol for controlling serial ports
    over telnet connections. It handles:
    - Telnet IAC (Interpret As Command) sequences
    - COM Port Control subnegotiations
    - Break signals
    - Control signals (DTR, RTS, etc.)
    - Line parameter negotiation
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.telnet_negotiation_pending = False
        self.in_iac_sequence = False
        self.iac_buffer = bytearray()
        self.data_callback = None

        # Track negotiated options
        self.binary_mode = False
        self.echo_mode = False
        self.sga_mode = False
        self.com_port_option = False

    async def negotiate_telnet_options(self):
        """
        Negotiate telnet options required for RFC2217.

        We need:
        - BINARY mode (to transmit all 8 bits)
        - SGA (Suppress Go Ahead)
        - COM_PORT_OPTION (RFC2217 commands)
        """
        # Request BINARY mode
        await self._send_iac_command(TelnetCmd.DO, TelnetOption.BINARY)
        await self._send_iac_command(TelnetCmd.WILL, TelnetOption.BINARY)

        # Request SGA (Suppress Go Ahead)
        await self._send_iac_command(TelnetCmd.DO, TelnetOption.SGA)
        await self._send_iac_command(TelnetCmd.WILL, TelnetOption.SGA)

        # Request COM Port Option
        await self._send_iac_command(TelnetCmd.DO, TelnetOption.COM_PORT_OPTION)
        await self._send_iac_command(TelnetCmd.WILL, TelnetOption.COM_PORT_OPTION)

        # Small delay to allow server to respond
        await asyncio.sleep(0.1)

    async def _send_iac_command(self, command: int, option: int):
        """Send a telnet IAC command."""
        self.writer.write(bytes([TelnetCmd.IAC, command, option]))
        await self.writer.drain()

    async def send_break(self, duration_ms: int = 250):
        """
        Send a BREAK signal to the serial port.

        Two methods:
        1. Telnet BREAK command (simple but less control)
        2. RFC2217 SET_CONTROL command (more precise)

        Args:
            duration_ms: Break duration in milliseconds (not always respected)
        """
        # Method 1: Simple telnet BREAK
        self.writer.write(bytes([TelnetCmd.IAC, TelnetCmd.BRK]))
        await self.writer.drain()

        # Method 2: RFC2217 BREAK via control signals
        # (Some servers prefer this method)
        # Note: RFC2217 doesn't specify BREAK duration directly,
        # so we simulate it by setting control signals

    async def set_control_signals(self, dtr: Optional[bool] = None,
                                  rts: Optional[bool] = None):
        """
        Set serial port control signals (DTR, RTS).

        Args:
            dtr: Data Terminal Ready state (True=ON, False=OFF, None=no change)
            rts: Request To Send state (True=ON, False=OFF, None=no change)
        """
        # Build control byte
        # We need to read current state first, but for simplicity
        # we'll set both if specified
        control = 0
        if dtr is not None:
            control |= ControlSignal.DTR if dtr else 0
        if rts is not None:
            control |= ControlSignal.RTS if rts else 0

        # Send RFC2217 SET_CONTROL command
        # Format: IAC SB COM_PORT_OPTION SET_CONTROL <value> IAC SE
        cmd_data = bytes([
            TelnetCmd.IAC,
            TelnetCmd.SB,
            TelnetOption.COM_PORT_OPTION,
            RFC2217Command.SET_CONTROL,
            control,
            TelnetCmd.IAC,
            TelnetCmd.SE
        ])
        self.writer.write(cmd_data)
        await self.writer.drain()

    async def set_baudrate(self, baudrate: int):
        """
        Set serial port baudrate.

        Args:
            baudrate: Baud rate (e.g., 9600, 115200)
        """
        # RFC2217 baudrate is sent as 4-byte network order (big-endian)
        baud_bytes = struct.pack('!I', baudrate)

        cmd_data = bytes([
            TelnetCmd.IAC,
            TelnetCmd.SB,
            TelnetOption.COM_PORT_OPTION,
            RFC2217Command.SET_BAUDRATE,
        ]) + baud_bytes + bytes([
            TelnetCmd.IAC,
            TelnetCmd.SE
        ])
        self.writer.write(cmd_data)
        await self.writer.drain()

    async def set_line_parameters(self, datasize: int = 8,
                                  parity: str = 'N',
                                  stopbits: int = 1):
        """
        Set serial line parameters.

        Args:
            datasize: Data bits (5, 6, 7, 8)
            parity: Parity ('N'=None, 'E'=Even, 'O'=Odd, 'M'=Mark, 'S'=Space)
            stopbits: Stop bits (1, 2)
        """
        # Set data size
        cmd = bytes([
            TelnetCmd.IAC, TelnetCmd.SB,
            TelnetOption.COM_PORT_OPTION,
            RFC2217Command.SET_DATASIZE,
            datasize,
            TelnetCmd.IAC, TelnetCmd.SE
        ])
        self.writer.write(cmd)

        # Set parity
        parity_map = {'N': 1, 'O': 2, 'E': 3, 'M': 4, 'S': 5}
        parity_val = parity_map.get(parity.upper(), 1)
        cmd = bytes([
            TelnetCmd.IAC, TelnetCmd.SB,
            TelnetOption.COM_PORT_OPTION,
            RFC2217Command.SET_PARITY,
            parity_val,
            TelnetCmd.IAC, TelnetCmd.SE
        ])
        self.writer.write(cmd)

        # Set stop bits
        cmd = bytes([
            TelnetCmd.IAC, TelnetCmd.SB,
            TelnetOption.COM_PORT_OPTION,
            RFC2217Command.SET_STOPSIZE,
            stopbits,
            TelnetCmd.IAC, TelnetCmd.SE
        ])
        self.writer.write(cmd)

        await self.writer.drain()

    async def send_data(self, data: bytes):
        """
        Send raw data to serial port.

        Must escape IAC bytes (0xFF) by doubling them (IAC IAC).
        """
        # Escape IAC bytes
        escaped = data.replace(bytes([TelnetCmd.IAC]),
                              bytes([TelnetCmd.IAC, TelnetCmd.IAC]))
        self.writer.write(escaped)
        await self.writer.drain()

    async def read_data(self) -> bytes:
        """
        Read data from serial port, handling telnet/RFC2217 protocol.

        Returns:
            Raw serial data (with telnet/RFC2217 sequences removed)
        """
        data = bytearray()

        while True:
            byte = await self.reader.read(1)
            if not byte:
                break

            b = byte[0]

            # Check for IAC sequence
            if b == TelnetCmd.IAC:
                # Read next byte to see what command follows
                next_byte = await self.reader.read(1)
                if not next_byte:
                    break

                nb = next_byte[0]

                # Escaped IAC (IAC IAC) = literal 0xFF data byte
                if nb == TelnetCmd.IAC:
                    data.append(TelnetCmd.IAC)

                # Telnet commands
                elif nb in (TelnetCmd.DO, TelnetCmd.DONT,
                           TelnetCmd.WILL, TelnetCmd.WONT):
                    # Read the option byte
                    opt = await self.reader.read(1)
                    if opt:
                        await self._handle_telnet_option(nb, opt[0])

                elif nb == TelnetCmd.SB:
                    # Subnegotiation - read until IAC SE
                    sb_data = await self._read_subnegotiation()
                    await self._handle_subnegotiation(sb_data)

                elif nb == TelnetCmd.BRK:
                    # Received BREAK from remote (unusual for client)
                    pass

                # For other commands, just ignore
                continue
            else:
                # Regular data byte
                data.append(b)

            # Return data as soon as we have some
            # (in interactive mode, don't buffer too much)
            if len(data) > 0:
                return bytes(data)

        return bytes(data)

    async def _read_subnegotiation(self) -> bytes:
        """Read subnegotiation data until IAC SE."""
        data = bytearray()
        while True:
            byte = await self.reader.read(1)
            if not byte:
                break
            b = byte[0]

            if b == TelnetCmd.IAC:
                next_byte = await self.reader.read(1)
                if not next_byte:
                    break
                nb = next_byte[0]
                if nb == TelnetCmd.SE:
                    # End of subnegotiation
                    return bytes(data)
                elif nb == TelnetCmd.IAC:
                    # Escaped IAC
                    data.append(TelnetCmd.IAC)
                else:
                    # Shouldn't happen, but add both bytes
                    data.append(b)
                    data.append(nb)
            else:
                data.append(b)

        return bytes(data)

    async def _handle_telnet_option(self, command: int, option: int):
        """Handle telnet option negotiation."""
        if command == TelnetCmd.DO:
            # Server asks us to enable an option
            if option == TelnetOption.BINARY:
                # Confirm BINARY mode
                await self._send_iac_command(TelnetCmd.WILL, option)
                self.binary_mode = True
            elif option == TelnetOption.SGA:
                # Confirm SGA
                await self._send_iac_command(TelnetCmd.WILL, option)
                self.sga_mode = True
            elif option == TelnetOption.COM_PORT_OPTION:
                # Confirm COM_PORT_OPTION
                await self._send_iac_command(TelnetCmd.WILL, option)
                self.com_port_option = True
            else:
                # Refuse other options
                await self._send_iac_command(TelnetCmd.WONT, option)

        elif command == TelnetCmd.WILL:
            # Server will enable an option
            if option in (TelnetOption.BINARY, TelnetOption.SGA,
                         TelnetOption.COM_PORT_OPTION):
                # Accept these options
                await self._send_iac_command(TelnetCmd.DO, option)
            else:
                # Refuse other options
                await self._send_iac_command(TelnetCmd.DONT, option)

        elif command == TelnetCmd.DONT:
            # Server asks us to disable an option
            await self._send_iac_command(TelnetCmd.WONT, option)

        elif command == TelnetCmd.WONT:
            # Server won't enable an option
            await self._send_iac_command(TelnetCmd.DONT, option)

    async def _handle_subnegotiation(self, data: bytes):
        """Handle RFC2217 subnegotiation."""
        if len(data) < 2:
            return

        option = data[0]
        command = data[1]

        if option == TelnetOption.COM_PORT_OPTION:
            # RFC2217 command
            if command == RFC2217Command.SIGNATURE:
                # Server signature (ignore for now)
                pass
            elif command == RFC2217Command.NOTIFY_LINESTATE:
                # Line state notification (e.g., errors)
                if len(data) > 2:
                    linestate = data[2]
                    # Could log or handle line state changes
            elif command == RFC2217Command.NOTIFY_MODEMSTATE:
                # Modem state notification (CTS, DSR, etc.)
                if len(data) > 2:
                    modemstate = data[2]
                    # Could log or handle modem state changes
            # Server responses to our SET commands (usually just echoed)
            # We can ignore most of these in a simple client


def write_stdout(data: bytes):
    """Write data to stdout (for terminal output)."""
    os.write(sys.stdout.fileno(), data)


async def shutdown(loop, signal=None):
    """Gracefully shutdown tasks."""
    if signal:
        write_stdout(f"\r\n[Received exit signal {signal.name}]\r\n".encode())

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


# ============================================================================
# Main Client Logic
# ============================================================================

async def bridge_rfc2217(host: str, port: int, line: int,
                        control_host: str, control_port: int,
                        want_writer: bool):
    """
    Bridge user terminal to serial port via RFC2217.

    This version connects directly to ser2net on the data plane port
    using RFC2217 protocol, while maintaining a separate control plane
    connection for session management.

    Args:
        host: ser2net host (data plane)
        port: ser2net port (data plane, e.g., 20001)
        line: serial line number
        control_host: control plane host
        control_port: control plane port
        want_writer: whether to request writer role
    """

    # Connect to control plane for authentication/session management
    ctrl_reader, ctrl_writer = await asyncio.open_connection(
        control_host, control_port)

    # Get username for session tracking
    user = os.environ.get("SSH_USER") or os.environ.get("LOGNAME") or \
           os.environ.get("USER")
    try:
        user = user or getpass.getuser()
    except Exception:
        user = user or "unknown"

    # Authenticate with control plane
    attach_msg = {
        "op": "attach",
        "line": line,
        "mode": "writer" if want_writer else "observer",
        "user": user
    }
    ctrl_writer.write(json.dumps(attach_msg).encode() + b"\n")
    await ctrl_writer.drain()

    write_stdout(b"\r\n[Connecting to ser2net via RFC2217]\r\n")

    # Wait for control plane to authorize
    auth_line = await ctrl_reader.readline()
    if not auth_line:
        write_stdout(b"[Control plane connection failed]\r\n")
        await shutdown(asyncio.get_running_loop())
        return

    auth_msg = json.loads(auth_line.decode())
    role = auth_msg.get("role", "observer")

    # If not authorized, wait for authorization
    # (In real implementation, control plane should provide ser2net details)

    # Connect to ser2net data plane
    try:
        data_reader, data_writer = await asyncio.open_connection(host, port)
    except Exception as e:
        write_stdout(f"[Failed to connect to ser2net: {e}]\r\n".encode())
        await shutdown(asyncio.get_running_loop())
        return

    # Initialize RFC2217 client
    rfc2217 = RFC2217Client(data_reader, data_writer)

    # Negotiate telnet/RFC2217 options
    await rfc2217.negotiate_telnet_options()

    write_stdout(f"[Attached as {role}]\r\n".encode())
    write_stdout(b"Escape commands:\r\n")
    write_stdout(b"  Ctrl-] q     : Quit\r\n")
    write_stdout(b"  Ctrl-] b     : Send BREAK\r\n")
    write_stdout(b"  Ctrl-] d     : Toggle DTR\r\n")
    write_stdout(b"  Ctrl-] r     : Toggle RTS\r\n")
    write_stdout(b"  Ctrl-] ?     : Help\r\n")

    # State variables
    escape_mode = False
    dtr_state = True
    rts_state = True

    async def control_plane_reader():
        """Handle control plane messages."""
        nonlocal role
        while True:
            line = await ctrl_reader.readline()
            if not line:
                write_stdout(b"\r\n[Control plane disconnected]\r\n")
                await shutdown(asyncio.get_running_loop())
                return

            msg = json.loads(line.decode())
            if msg.get("op") == "role":
                role = msg.get("role", role)
                write_stdout(f"[Role changed to {role}]\r\n".encode())
            elif msg.get("op") == "detach":
                write_stdout(b"\r\n[Detached by server]\r\n")
                await shutdown(asyncio.get_running_loop())
                return

    async def serial_data_reader():
        """Read data from serial port via RFC2217."""
        while True:
            try:
                data = await rfc2217.read_data()
                if not data:
                    write_stdout(b"\r\n[Serial connection closed]\r\n")
                    await shutdown(asyncio.get_running_loop())
                    return
                write_stdout(data)
            except Exception as e:
                write_stdout(f"\r\n[Read error: {e}]\r\n".encode())
                await shutdown(asyncio.get_running_loop())
                return

    async def stdin_reader():
        """Read from stdin and handle escape sequences."""
        nonlocal escape_mode, dtr_state, rts_state
        loop = asyncio.get_running_loop()

        while True:
            try:
                chunk = await loop.run_in_executor(None, os.read,
                                                   sys.stdin.fileno(), 1024)
                if not chunk:
                    break

                for byte in chunk:
                    # Check for escape character (Ctrl-], ASCII 29)
                    if byte == 29:  # Ctrl-]
                        escape_mode = True
                        write_stdout(b"\r\n[Escape mode - press ? for help]\r\n")
                        continue

                    if escape_mode:
                        escape_mode = False

                        if byte == ord('q') or byte == ord('Q'):
                            # Quit
                            write_stdout(b"\r\n[Quitting]\r\n")
                            ctrl_writer.write(json.dumps(
                                {"op": "detach"}).encode() + b"\n")
                            await ctrl_writer.drain()
                            await shutdown(asyncio.get_running_loop())
                            return

                        elif byte == ord('b') or byte == ord('B'):
                            # Send BREAK
                            write_stdout(b"\r\n[Sending BREAK]\r\n")
                            await rfc2217.send_break()

                        elif byte == ord('d') or byte == ord('D'):
                            # Toggle DTR
                            dtr_state = not dtr_state
                            await rfc2217.set_control_signals(dtr=dtr_state)
                            state = "ON" if dtr_state else "OFF"
                            write_stdout(f"\r\n[DTR {state}]\r\n".encode())

                        elif byte == ord('r') or byte == ord('R'):
                            # Toggle RTS
                            rts_state = not rts_state
                            await rfc2217.set_control_signals(rts=rts_state)
                            state = "ON" if rts_state else "OFF"
                            write_stdout(f"\r\n[RTS {state}]\r\n".encode())

                        elif byte == ord('?'):
                            # Help
                            write_stdout(b"\r\n[Escape Commands]\r\n")
                            write_stdout(b"  q : Quit\r\n")
                            write_stdout(b"  b : Send BREAK\r\n")
                            write_stdout(b"  d : Toggle DTR\r\n")
                            write_stdout(b"  r : Toggle RTS\r\n")
                            write_stdout(b"  ? : This help\r\n")
                        else:
                            write_stdout(b"\r\n[Unknown escape command]\r\n")
                        continue

                    # Normal data - send to serial port
                    if role == "writer":
                        await rfc2217.send_data(bytes([byte]))
                    # Observers can't send data

            except Exception as e:
                write_stdout(f"\r\n[Input error: {e}]\r\n".encode())
                break

    # Run all tasks concurrently
    await asyncio.gather(
        control_plane_reader(),
        serial_data_reader(),
        stdin_reader()
    )


async def bridge_simple(host: str, port: int, line: int, want_writer: bool):
    """
    Simple direct RFC2217 connection without separate control plane.

    This is useful for testing or when authentication is handled elsewhere
    (e.g., via SSH port forwarding).
    """
    write_stdout(b"\r\n[Connecting directly to ser2net]\r\n")

    try:
        reader, writer = await asyncio.open_connection(host, port)
    except Exception as e:
        write_stdout(f"[Connection failed: {e}]\r\n".encode())
        return

    rfc2217 = RFC2217Client(reader, writer)
    await rfc2217.negotiate_telnet_options()

    write_stdout(b"[Connected]\r\n")
    write_stdout(b"Ctrl-] for escape commands\r\n")

    escape_mode = False
    dtr_state = True
    rts_state = True

    async def serial_data_reader():
        """Read from serial port."""
        while True:
            try:
                data = await rfc2217.read_data()
                if not data:
                    write_stdout(b"\r\n[Connection closed]\r\n")
                    await shutdown(asyncio.get_running_loop())
                    return
                write_stdout(data)
            except Exception as e:
                write_stdout(f"\r\n[Error: {e}]\r\n".encode())
                await shutdown(asyncio.get_running_loop())
                return

    async def stdin_reader():
        """Read from stdin."""
        nonlocal escape_mode, dtr_state, rts_state
        loop = asyncio.get_running_loop()

        while True:
            chunk = await loop.run_in_executor(None, os.read,
                                              sys.stdin.fileno(), 1024)
            if not chunk:
                break

            for byte in chunk:
                if byte == 29:  # Ctrl-]
                    escape_mode = True
                    write_stdout(b"\r\n[Escape: ? for help]\r\n")
                    continue

                if escape_mode:
                    escape_mode = False
                    if byte == ord('q'):
                        await shutdown(asyncio.get_running_loop())
                        return
                    elif byte == ord('b'):
                        await rfc2217.send_break()
                        write_stdout(b"\r\n[BREAK sent]\r\n")
                    elif byte == ord('d'):
                        dtr_state = not dtr_state
                        await rfc2217.set_control_signals(dtr=dtr_state)
                        write_stdout(f"\r\n[DTR {'ON' if dtr_state else 'OFF'}]\r\n".encode())
                    elif byte == ord('r'):
                        rts_state = not rts_state
                        await rfc2217.set_control_signals(rts=rts_state)
                        write_stdout(f"\r\n[RTS {'ON' if rts_state else 'OFF'}]\r\n".encode())
                    elif byte == ord('?'):
                        write_stdout(b"\r\nq:Quit b:Break d:DTR r:RTS\r\n")
                    continue

                await rfc2217.send_data(bytes([byte]))

    await asyncio.gather(serial_data_reader(), stdin_reader())


async def main():
    import argparse
    p = argparse.ArgumentParser(description="RFC2217 serial console client")
    p.add_argument("--host", default="127.0.0.1",
                  help="ser2net host (data plane)")
    p.add_argument("--port", type=int, default=20001,
                  help="ser2net port (data plane)")
    p.add_argument("--line", type=int, default=1,
                  help="serial line number")
    p.add_argument("--control-host", default="127.0.0.1",
                  help="control plane host")
    p.add_argument("--control-port", type=int, default=25001,
                  help="control plane port")
    p.add_argument("--observer", action="store_true",
                  help="attach as observer (read-only)")
    p.add_argument("--simple", action="store_true",
                  help="simple mode (no control plane, direct connection)")
    args = p.parse_args()

    loop = asyncio.get_event_loop()

    if args.simple:
        main_task = loop.create_task(bridge_simple(args.host, args.port, args.line,
                          want_writer=not args.observer))
    else:
        main_task = loop.create_task(bridge_rfc2217(args.host, args.port, args.line,
                           args.control_host, args.control_port,
                           want_writer=not args.observer))

    try:
        loop.run_forever()
    finally:
        main_task.cancel()
        loop.run_until_complete(main_task)
        loop.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
