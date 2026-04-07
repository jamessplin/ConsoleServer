# RFC2217: COM Port Control Protocol - Deep Dive

## Overview

RFC2217 is a protocol that extends Telnet to support **remote serial port control** over TCP/IP networks. It allows a client to not only transmit/receive raw serial data but also control serial port parameters and signals (like DTR, RTS, baud rate, etc.) as if the serial port were locally connected.

## Why RFC2217?

Traditional telnet or raw socket connections can transmit serial **data**, but they cannot:
- Send BREAK signals
- Control hardware flow control (RTS/CTS)
- Set DTR/DSR states
- Change baud rates dynamically
- Configure parity, data bits, stop bits
- Query modem/line status

RFC2217 solves these limitations by defining a **control protocol** layered on top of Telnet.

---

## Architecture: Data vs Control

### Without RFC2217 (Raw Telnet/Socket)
```
Client Terminal
      |
      | (raw bytes only)
      v
  TCP Socket (telnet)
      |
      v
   ser2net
      |
      v
Serial Device (/dev/ttyUSB0)
```

**Limitations:**
- Only byte data flows
- No control over serial parameters
- No BREAK signal support
- No hardware handshaking control

### With RFC2217
```
Client Terminal
      |
      | (data + control commands)
      v
RFC2217 Client
      |
      +---> Data Path: Raw serial bytes (escaped)
      |
      +---> Control Path: IAC sequences
      |          - BREAK signals
      |          - SET baudrate
      |          - SET control signals (DTR/RTS)
      |          - NOTIFY modem state
      v
  TCP Socket (RFC2217 over telnet)
      |
      v
ser2net (RFC2217 server)
      |
      +---> Translates to serial port actions
      v
Serial Device (/dev/ttyUSB0)
```

---

## Protocol Layers

RFC2217 operates as a **Telnet option** (option 44: COM-PORT-CONTROL). It uses Telnet's IAC (Interpret As Command) mechanism to multiplex data and control.

### Layer Stack
```
┌─────────────────────────────────────┐
│   Application (serial console)     │
├─────────────────────────────────────┤
│   RFC2217 Protocol Layer            │
│   - COM port commands                │
│   - IAC subnegotiations              │
├─────────────────────────────────────┤
│   Telnet Protocol Layer              │
│   - IAC sequences                    │
│   - Option negotiation               │
├─────────────────────────────────────┤
│   TCP Socket                         │
└─────────────────────────────────────┘
```

---

## Telnet Basics (Foundation for RFC2217)

### IAC (Interpret As Command)
Telnet uses byte `0xFF` (255) as an **escape character** called IAC.

**Key IAC Commands:**
- `IAC WILL <option>` - "I will use this option"
- `IAC DO <option>` - "Please use this option"
- `IAC WONT <option>` - "I won't use this option"
- `IAC DONT <option>` - "Don't use this option"
- `IAC SB <option> <data> IAC SE` - Subnegotiation (send complex data for an option)
- `IAC BRK` - Break signal (simple method)

### Example: Negotiating Binary Mode
```
Client → Server:  FF FD 00  (IAC DO BINARY)     "Please send binary data"
Server → Client:  FF FB 00  (IAC WILL BINARY)   "OK, I will send binary"
Client → Server:  FF FB 00  (IAC WILL BINARY)   "I will also send binary"
Server → Client:  FF FD 00  (IAC DO BINARY)     "OK, please do"
```

**After negotiation:** Both sides can transmit all 8-bit bytes (0x00-0xFF).

### Data Escaping
Since `0xFF` is IAC, to send literal `0xFF` as data:
- Send: `FF FF` (IAC IAC)
- Receives as: `FF` (single byte)

---

## RFC2217 Specific Features

### COM Port Control Option (44)

RFC2217 defines **Telnet Option 44**: COM-PORT-CONTROL

**Subnegotiation Format:**
```
IAC SB COM-PORT-CONTROL <command> <parameters> IAC SE
```

Where:
- `IAC` = 0xFF
- `SB` = 0xFA (subnegotiation begin)
- `COM-PORT-CONTROL` = 44 (0x2C)
- `<command>` = RFC2217 command code
- `<parameters>` = command-specific data
- `SE` = 0xF0 (subnegotiation end)

### RFC2217 Commands

| Command Code | Name | Direction | Purpose |
|--------------|------|-----------|---------|
| 0 | SIGNATURE | Both | Server/client identification |
| 1 | SET_BAUDRATE | Client→Server | Set baud rate |
| 2 | SET_DATASIZE | Client→Server | Set data bits (5,6,7,8) |
| 3 | SET_PARITY | Client→Server | Set parity (None, Even, Odd, Mark, Space) |
| 4 | SET_STOPSIZE | Client→Server | Set stop bits (1, 2) |
| 5 | SET_CONTROL | Client→Server | Set control signals (DTR, RTS) |
| 6 | NOTIFY_LINESTATE | Server→Client | Line state changes (errors, break) |
| 7 | NOTIFY_MODEMSTATE | Server→Client | Modem state (CTS, DSR, RI, DCD) |
| 8 | FLOWCONTROL_SUSPEND | Both | Software flow control (XOFF) |
| 9 | FLOWCONTROL_RESUME | Both | Software flow control (XON) |
| 10 | SET_LINESTATE_MASK | Client→Server | Which line states to notify |
| 11 | SET_MODEMSTATE_MASK | Client→Server | Which modem states to notify |
| 12 | PURGE_DATA | Client→Server | Flush buffers |

---

## Detailed Examples

### Example 1: Setting Baud Rate to 115200

**Client sends:**
```
FF FA 2C 01 00 01 C2 00 FF F0
│  │  │  │  └─────┬──────┘ │  │
│  │  │  │        │        │  └─ SE (end subnegotiation)
│  │  │  │        │        └──── IAC
│  │  │  │        └───────────── 115200 (0x0001C200 in network byte order)
│  │  │  └────────────────────── Command 1: SET_BAUDRATE
│  │  └───────────────────────── Option 44: COM-PORT-CONTROL
│  └──────────────────────────── SB (subnegotiation begin)
└─────────────────────────────── IAC
```

**Breakdown:**
1. IAC SB - Start subnegotiation
2. 0x2C (44) - COM-PORT-CONTROL option
3. 0x01 - SET_BAUDRATE command
4. 0x00 0x01 0xC2 0x00 - 115200 as 32-bit big-endian integer
5. IAC SE - End subnegotiation

**Server response (echo):**
```
FF FA 2C 65 00 01 C2 00 FF F0
                │
                └── 0x65 = 101 = command + 100 (server response)
```

Server typically echoes with command code + 100 to confirm.

### Example 2: Sending BREAK Signal

**Method 1: Simple Telnet BREAK**
```
Client → Server: FF F3  (IAC BRK)
```
This is the simplest method but offers no duration control.

**Method 2: Via Control Signals (More Control)**
Some implementations use SET_CONTROL to assert break:
```
FF FA 2C 05 10 FF F0
            │
            └─ 0x10 = BREAK bit in control signals
```

### Example 3: Setting DTR and RTS

**Set DTR=ON, RTS=ON:**
```
FF FA 2C 05 03 FF F0
            │
            └─ 0x03 = 0x01 (DTR) | 0x02 (RTS)
```

**Control Signal Bits:**
- Bit 0 (0x01): DTR (Data Terminal Ready)
- Bit 1 (0x02): RTS (Request To Send)
- Bit 4 (0x10): CTS (Clear To Send) - read-only
- Bit 5 (0x20): DSR (Data Set Ready) - read-only
- Bit 6 (0x40): RI (Ring Indicator) - read-only
- Bit 7 (0x80): DCD (Data Carrier Detect) - read-only

**Set DTR=OFF, RTS=ON:**
```
FF FA 2C 05 02 FF F0
            │
            └─ 0x02 = RTS only
```

### Example 4: Receiving Modem State Notification

**Server notifies: CTS=ON, DSR=ON**
```
Server → Client: FF FA 2C 6B 30 FF F0
                           │
                           └─ 0x30 = 0x10 (CTS) | 0x20 (DSR)
```

Command 0x6B = 107 = NOTIFY_MODEMSTATE (7) + 100 (server notification).

---

## Data Transmission with RFC2217

### Sending Raw Serial Data

**Key Rule:** Escape IAC bytes (0xFF) by doubling them.

**Example: Sending "Hello\xFF"**
```
Original data: 48 65 6C 6C 6F FF

Transmitted:   48 65 6C 6C 6F FF FF
                                │  │
                                └──┴── Escaped IAC
```

**Python Code:**
```python
def send_serial_data(data: bytes):
    # Escape 0xFF bytes
    escaped = data.replace(b'\xff', b'\xff\xff')
    socket.send(escaped)
```

### Receiving Raw Serial Data

**Process incoming bytes:**
1. If byte is NOT IAC (0xFF):
   - It's serial data → pass to application
2. If byte IS IAC (0xFF):
   - Read next byte:
     - If next is IAC → Single 0xFF data byte
     - If next is command (WILL, DO, SB, etc.) → Handle telnet/RFC2217 command
     - If next is BRK → Break signal received

**Python Code:**
```python
async def receive_serial_data(reader):
    while True:
        byte = await reader.read(1)
        b = byte[0]

        if b == 0xFF:  # IAC
            next_byte = await reader.read(1)
            nb = next_byte[0]

            if nb == 0xFF:  # Escaped IAC - real data
                yield bytes([0xFF])
            elif nb == 0xFA:  # SB - subnegotiation
                sb_data = await read_subnegotiation(reader)
                handle_rfc2217_command(sb_data)
            elif nb in (0xFB, 0xFC, 0xFD, 0xFE):  # WILL, WONT, DO, DONT
                option = await reader.read(1)
                handle_telnet_option(nb, option[0])
            # ... handle other IAC commands
        else:
            # Regular data byte
            yield bytes([b])
```

---

## Complete Connection Flow

### 1. TCP Connection
```
Client connects to ser2net:20001
```

### 2. Telnet Option Negotiation
```
Client → Server: FF FD 00  (IAC DO BINARY)
Server → Client: FF FB 00  (IAC WILL BINARY)
Client → Server: FF FB 00  (IAC WILL BINARY)
Server → Client: FF FD 00  (IAC DO BINARY)

Client → Server: FF FD 03  (IAC DO SUPPRESS-GO-AHEAD)
Server → Client: FF FB 03  (IAC WILL SUPPRESS-GO-AHEAD)

Client → Server: FF FD 2C  (IAC DO COM-PORT-CONTROL)
Server → Client: FF FB 2C  (IAC WILL COM-PORT-CONTROL)
Client → Server: FF FB 2C  (IAC WILL COM-PORT-CONTROL)
Server → Client: FF FD 2C  (IAC DO COM-PORT-CONTROL)
```

**Result:** Both sides agree to use:
- Binary mode (transmit all 8 bits)
- SGA (no Go-Ahead needed)
- COM-PORT-CONTROL (RFC2217 enabled)

### 3. Serial Port Configuration (Optional)
```
Client → Server: Set baudrate to 115200
Client → Server: Set 8N1 (8 data bits, no parity, 1 stop bit)
Client → Server: Set DTR=ON, RTS=ON
```

### 4. Data Exchange
```
User types: "ls\n"
Client → Server: 6C 73 0A  (escaped if needed)

Serial device outputs: "file1.txt\n"
Server → Client: 66 69 6C 65 31 2E 74 78 74 0A

User presses Ctrl-] b (escape + break command)
Client → Server: FF F3  (IAC BRK)
```

### 5. Disconnection
```
Client closes TCP connection
```

---

## Practical Use Cases

### 1. Remote Serial Console Access
```
[Admin laptop] --RFC2217--> [ser2net server] --serial--> [Embedded device console]
```
Admin can:
- See console output
- Type commands
- Send BREAK to enter bootloader
- Control DTR to reset device

### 2. Serial Port Sharing
Multiple clients can connect (read-only observers + one writer):
```
[Client 1 (writer)] ─┐
[Client 2 (observer)]├─ RFC2217 ─> ser2net -> /dev/ttyUSB0
[Client 3 (observer)]─┘
```

### 3. Serial Device Testing
Automated tests can:
- Set baud rate programmatically
- Toggle control signals (DTR/RTS)
- Send BREAK at specific times
- Monitor CTS/DSR states

### 4. Remote Firmware Upgrade
```python
# Connect via RFC2217
rfc2217 = RFC2217Client(host, port)

# Reset device into bootloader
await rfc2217.set_control_signals(dtr=False)
await asyncio.sleep(0.1)
await rfc2217.set_control_signals(dtr=True)

# Send break to enter bootloader menu
await rfc2217.send_break()

# Upload firmware
await rfc2217.send_data(firmware_bytes)
```

---

## Comparison: Raw Socket vs Telnet vs RFC2217

| Feature | Raw Socket | Telnet | RFC2217 |
|---------|-----------|--------|---------|
| Data TX/RX | ✅ | ✅ | ✅ |
| BREAK signal | ❌ | ✅ (IAC BRK) | ✅ (IAC BRK + control) |
| DTR/RTS control | ❌ | ❌ | ✅ |
| Baud rate change | ❌ | ❌ | ✅ |
| Parity/bits config | ❌ | ❌ | ✅ |
| CTS/DSR monitoring | ❌ | ❌ | ✅ |
| Line state events | ❌ | ❌ | ✅ |
| Data escaping | ❌ | ✅ (IAC IAC) | ✅ (IAC IAC) |

---

## Python Implementation Examples

### Basic RFC2217 Client

```python
import asyncio

class RFC2217Client:
    def __init__(self, host, port):
        self.host = host
        self.port = port

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(
            self.host, self.port)
        await self._negotiate()

    async def _negotiate(self):
        # Negotiate BINARY mode
        self.writer.write(b'\xff\xfd\x00')  # IAC DO BINARY
        self.writer.write(b'\xff\xfb\x00')  # IAC WILL BINARY

        # Negotiate COM-PORT-CONTROL
        self.writer.write(b'\xff\xfd\x2c')  # IAC DO COM-PORT-CONTROL
        self.writer.write(b'\xff\xfb\x2c')  # IAC WILL COM-PORT-CONTROL

        await self.writer.drain()
        await asyncio.sleep(0.1)  # Wait for server response

    async def send_data(self, data: bytes):
        # Escape IAC bytes
        escaped = data.replace(b'\xff', b'\xff\xff')
        self.writer.write(escaped)
        await self.writer.drain()

    async def send_break(self):
        self.writer.write(b'\xff\xf3')  # IAC BRK
        await self.writer.drain()

    async def set_baudrate(self, baud: int):
        cmd = b'\xff\xfa\x2c\x01'  # IAC SB COM-PORT 1:SET_BAUDRATE
        cmd += baud.to_bytes(4, 'big')
        cmd += b'\xff\xf0'  # IAC SE
        self.writer.write(cmd)
        await self.writer.drain()

    async def set_control(self, dtr: bool, rts: bool):
        control = 0
        if dtr:
            control |= 0x01
        if rts:
            control |= 0x02
        cmd = b'\xff\xfa\x2c\x05' + bytes([control]) + b'\xff\xf0'
        self.writer.write(cmd)
        await self.writer.drain()

    async def read_data(self):
        """Read and return serial data (handle IAC escaping)"""
        result = bytearray()

        while True:
            byte = await self.reader.read(1)
            if not byte:
                break

            if byte[0] == 0xFF:  # IAC
                next_byte = await self.reader.read(1)
                if next_byte[0] == 0xFF:  # Escaped IAC
                    result.append(0xFF)
                elif next_byte[0] == 0xFA:  # Subnegotiation
                    await self._handle_subnegotiation()
                # ... handle other commands
            else:
                result.append(byte[0])

            # Return when we have some data
            if len(result) > 0:
                return bytes(result)

        return bytes(result)

# Usage
async def main():
    client = RFC2217Client('192.168.1.100', 20001)
    await client.connect()

    # Set serial parameters
    await client.set_baudrate(115200)
    await client.set_control(dtr=True, rts=True)

    # Send command
    await client.send_data(b'help\r\n')

    # Read response
    response = await client.read_data()
    print(response)

    # Send break
    await client.send_break()

asyncio.run(main())
```

### Using pySerial's Built-in RFC2217

PySerial includes RFC2217 support:

```python
import serial

# Connect using RFC2217 URL
ser = serial.serial_for_url('rfc2217://192.168.1.100:20001')

# Now use like a normal serial port
ser.baudrate = 115200
ser.write(b'hello\n')
data = ser.read(100)

# Send break
ser.send_break(duration=0.25)

# Control signals
ser.dtr = True
ser.rts = True

ser.close()
```

---

## ser2net Configuration for RFC2217

### ser2net 4.x (YAML format)

```yaml
connection: &console1
  accepter: tcp,20001
  enable: on
  options:
    kickolduser: true
    telnet-brk-on-sync: true  # Enable BREAK via telnet
  connector: serialdev,/dev/ttyUSB0,115200n81,local,nobreak
```

**Key Options:**
- `telnet-brk-on-sync: true` - Handle IAC BRK commands
- `kickolduser: true` - Disconnect previous user on new connection
- `nobreak` in connector - Prevents spurious breaks during connection

### ser2net 3.x (Classic format)

```
20001:telnet:0:/dev/ttyUSB0:115200 8DATABITS NONE 1STOPBIT banner
```

---

## Security Considerations

### 1. No Built-in Encryption
RFC2217 (like telnet) has **no encryption**. Solutions:
- Use SSH tunneling: `ssh -L 20001:localhost:20001 user@server`
- VPN
- TLS wrapper (stunnel)

### 2. No Authentication
RFC2217 itself doesn't authenticate users. Add:
- SSH-based access control
- Separate authentication layer (like in our console server)
- Firewall rules

### 3. Shared Serial Port Access
Multiple users can connect - implement:
- Role-based access (writer vs observer)
- Audit logging
- Session takeover controls

---

## Debugging RFC2217 Connections

### Packet Capture with Wireshark

Filter: `tcp.port == 20001`

Look for:
- IAC sequences (0xFF)
- Subnegotiations (0xFF 0xFA ... 0xFF 0xF0)
- COM-PORT-CONTROL option (0x2C)

### Hex Dump Example

```
0000: ff fd 00 ff fb 00 ff fd 2c   ........,
      IAC DO BINARY, IAC WILL BINARY, IAC DO COM-PORT

0009: ff fb 2c                      ..,
      IAC WILL COM-PORT

000c: 68 65 6c 6c 6f 0a            hello.
      Regular data: "hello\n"

0012: ff fa 2c 6b 30 ff f0         ..,k0..
      IAC SB COM-PORT 107(MODEM-STATE) 0x30 IAC SE
```

### Enable Logging in Client

```python
class RFC2217Client:
    def __init__(self, ..., debug=False):
        self.debug = debug

    def _log(self, msg):
        if self.debug:
            print(f"[RFC2217] {msg}", file=sys.stderr)

    async def send_data(self, data):
        self._log(f"TX data: {data.hex()}")
        # ... send data
```

---

## Summary

**RFC2217 provides:**
1. **Data Path**: TX/RX serial bytes (with IAC escaping)
2. **Control Path**:
   - BREAK signals
   - DTR/RTS control
   - Baud rate, parity, data bits, stop bits configuration
   - CTS/DSR/DCD/RI monitoring
   - Line state notifications

**Key Components:**
- Built on top of Telnet (IAC mechanism)
- Uses Telnet Option 44 (COM-PORT-CONTROL)
- Subnegotiation for complex commands
- Bidirectional: client controls, server notifies

**Advantages over plain telnet:**
- Full serial port control
- Programmatic configuration changes
- Hardware flow control support
- Break signal support

**Best for:**
- Remote serial console access
- Automated serial device testing
- Serial port sharing/multiplexing
- Embedded system development and debugging

The client implementation in `client_rfc2217.py` demonstrates practical usage with both data transmission and control signal handling.
