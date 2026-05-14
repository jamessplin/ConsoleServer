#!/usr/bin/env python3

import asyncio
import base64
import json
import re
import threading
import queue
import time
from dataclasses import dataclass
import logging
import sys
from collections import deque
from typing import Dict, Set, Optional

# Logging setup: change level to logging.DEBUG for debug, logging.INFO for normal
logging.basicConfig(
    level=logging.DEBUG,  # Change to logging.DEBUG for more output
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('/var/log/seriald.log'),
        logging.StreamHandler(sys.stdout)
    ]
)


# Role utility (inlined from role_utils.py)
import os
import sys
import json
from enum import Enum
from typing import Optional

# Define your role priorities here
ROLE_PRIORITY = [
    "admin",
    "console_user",
    "operator",
    "none"
]

class UserRole(Enum):
    ADMIN = "admin"
    CONSOLE_USER = "console_user"
    OPERATOR = "operator"
    NONE = "none"

# Define default values for new users and groups
USER_DEFAULT_GROUP = ["Group_Default"]  # default to access to all ports, can be overridden
USER_DEFAULT_ROLE = UserRole.NONE.value
GROUP_DEFAULT_PORTS = list(range(1, 25))  # default to access to all ports, can be overridden
GROUP_DEFAULT_ROLE = UserRole.CONSOLE_USER.value

USERNAME_MAX_LENGTH = 32
PASSWORD_MAX_LENGTH = 128
GROUPNAME_MAX_LENGTH = 32
USERNAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_username(username: str) -> Optional[str]:
    if not isinstance(username, str) or not username:
        return "missing username"
    if len(username) > USERNAME_MAX_LENGTH:
        return f"username must be <= {USERNAME_MAX_LENGTH} characters"
    if not USERNAME_PATTERN.match(username):
        return "username must start with a letter or underscore and contain only letters, digits, or underscore"
    return None


def validate_password(password: str) -> Optional[str]:
    if not isinstance(password, str):
        return "password must be a string"
    if not password:
        return "password cannot be empty"
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"password must be <= {PASSWORD_MAX_LENGTH} characters"
    return None


def validate_groupname(groupname: str) -> Optional[str]:
    if not isinstance(groupname, str) or not groupname:
        return "missing groupname"
    if len(groupname) > GROUPNAME_MAX_LENGTH:
        return f"groupname must be <= {GROUPNAME_MAX_LENGTH} characters"
    return None


LABEL_MAX_LENGTH = 16

def validate_label(label: str) -> Optional[str]:
    if not isinstance(label, str):
        return "label must be a string"
    if len(label) > LABEL_MAX_LENGTH:
        return f"label must be <= {LABEL_MAX_LENGTH} characters"
    return None


def get_effective_role(username: str, config) -> Optional[str]:
    """
    Determine the effective role for a user based on config (dict or path).
    User's own role takes precedence if set. Otherwise, the highest priority group role is used.
    """
    if isinstance(config, str):
        # If config is a path, load it
        with open(config, 'r') as f:
            config = json.load(f)
    users = config.get("users", {})
    groups = config.get("groups", {})
    user = users.get(username)
    if not user:
        return None
    user_role = user.get("role")
    # "none" means no user-specific override; inherit from group role.
    if user_role and user_role != UserRole.NONE.value:
        return user_role
    # If user role is empty/null, check group roles
    user_groups = user.get("groups", [])
    group_roles = [groups[g].get("role") for g in user_groups if g in groups and groups[g].get("role")]
    if not group_roles:
        return None
    # Find the highest priority role among all group roles
    group_roles_set = set(group_roles)
    for role in ROLE_PRIORITY:
        if role in group_roles_set:
            return role
    return group_roles[0]  # fallback if no match in priority

# --- Backend demo (replace with pyserial for real devices) ---
class FakeSerialDevice:
    def __init__(self):
        self.rx = queue.Queue()
        self.tx = queue.Queue()
        self.running = False
        self._thread = None
        # simple login state machine
        self._expect = "username"  # or "password" or "shell"
        self._last_user = None

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def send(self, data: bytes):
        self.rx.put(data)

    def recv(self, timeout=0.1):
        try:
            return self.tx.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        time.sleep(0.2)
        self.tx.put(b"\r\nBooting device...\r\nlogin: ")
        while self.running:
            try:
                data = self.rx.get(timeout=0.1)
                cmd = data.strip()
                # handle simple login conversation
                if self._expect == "username":
                    if cmd:
                        self._last_user = cmd
                        self._expect = "password"
                        self.tx.put(b"\r\nPassword: ")
                    else:
                        self.tx.put(b"\r\nlogin: ")
                elif self._expect == "password":
                    user = (self._last_user or b"")
                    pw = cmd or b""
                    ok = (user == b"admin" and pw == b"password") or (user == b"bob" and pw == b"bob")
                    if ok:
                        self._expect = "shell"
                        self.tx.put(b"\r\nWelcome!\r\n# ")
                    else:
                        # reset login
                        self._expect = "username"
                        self._last_user = None
                        self.tx.put(b"\r\nLogin incorrect\r\nlogin: ")
                else:  # shell
                    # very simple shell: echo unknown command and show prompt
                    if cmd in (b"exit", b"logout"):
                        # Simulate logout to login prompt
                        self._expect = "username"
                        self._last_user = None
                        self.tx.put(b"\r\nlogout\r\nlogin: ")
                    else:
                        self.tx.put(b"\r\nunknown command: " + cmd + b"\r\n# ")
            except queue.Empty:
                pass

# --- Daemon state ---
# Use identity-based hashing so instances can live in sets
@dataclass(eq=False)
class Client:
    writer: asyncio.StreamWriter
    line_id: int | None = None
    can_write: bool = False
    user: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None


# Global reference to the running SerialDaemon instance (if any)
_serial_daemon_instance = None

def get_user_role_api(username: str, config_path: str = None):
    """
    Get the effective role for a user, using in-memory config if available, else fallback to config.json.
    """
    logging.info(f"Getting role for user: {username}")
    global _serial_daemon_instance
    if _serial_daemon_instance and hasattr(_serial_daemon_instance, 'config'):
        config = _serial_daemon_instance.config
        logging.debug("Using in-memory config for role lookup")
        return get_effective_role(username, config)
    # Fallback to config.json on disk
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    logging.debug(f"Falling back to config file: {config_path}")
    return get_effective_role(username, config_path)

import signal
import functools

class SerialDaemon:
    def __init__(self, config: Optional[dict] = None, config_path: Optional[str] = None):
        global _serial_daemon_instance
        _serial_daemon_instance = self

        self.config_path = config_path or os.path.join(os.path.dirname(__file__), "config.json")

        # config: per-line settings
        self.config = config or self._load_config()

        # Main asyncio server
        self.server: Optional[asyncio.Server] = None
        # ser2net subprocesses managed by this server
        self.ser2net_processes: Dict[int, asyncio.subprocess.Process] = {}
        # Load users and groups for RBAC
        self.users = self.config.get("users", {})
        self.groups = self.config.get("groups", {})
        # per-line backend (e.g. FakeSerialDevice or PySerialBackend)
        self.backends: Dict[int, FakeSerialDevice | None] = {}
        # per-line client sets
        self.clients_by_line: Dict[int, Set[Client]] = {}
        # per-line active writer (exclusive mode)
        self.active_writer: Dict[int, Client | None] = {}
        # per-line observer queue (exclusive mode)
        self.observer_queue: Dict[int, deque[Client]] = {}
        # per-line micro-lock for windowed access (shared mode)
        self.line_lock: Dict[int, asyncio.Lock] = {}
        # per-line serial->client background tasks
        self._rx_tasks: Dict[int, asyncio.Task] = {}
        # Track last client activity for idle timeout
        self._last_activity: Dict[Client, float] = {}
        # Keepalive config
        try:
            ka_ms = int((self.config or {}).get("keepalive_ms", 15000))
        except Exception:
            ka_ms = 15000
        self.keepalive_interval: float = max(5.0, ka_ms / 1000.0)
        self._keepalive_task: Optional[asyncio.Task] = None
        # Start idle timeout pruning task
        self._idle_timeout_task: Optional[asyncio.Task] = None
        # Event to signal shutdown
        self._shutdown_event = asyncio.Event()

        # Load user and group limits
        info = self.config.get("info", {})
        self.user_limit = info.get("no_of_user", 32)
        self.group_limit = info.get("no_of_group", 32)
        self.port_limit = info.get("no_of_port")

        # Validate startup config against configured port limit.
        self._validate_existing_group_ports()

    def _get_port_limit(self) -> Optional[int]:
        """Return configured no_of_port as an int, or None if not configured/invalid."""
        try:
            limit = int(self.port_limit)
        except Exception:
            return None
        return limit if limit >= 1 else None

    def _validate_group_port_list(self, ports) -> Optional[str]:
        """Validate group port_list entries against info.no_of_port."""
        limit = self._get_port_limit()
        if limit is None:
            return None

        if not isinstance(ports, list):
            return "ports must be a list"

        for p in ports:
            try:
                port_num = int(p)
            except Exception:
                return f"invalid port '{p}': must be an integer between 1 and {limit}"
            if port_num < 1 or port_num > limit:
                return f"invalid port '{port_num}': must be between 1 and {limit}"
        return None

    def _validate_existing_group_ports(self):
        """Validate all configured groups on startup; log if any ports exceed no_of_port."""
        groups = (self.config or {}).get("groups", {})
        for groupname, group_data in groups.items():
            err = self._validate_group_port_list(group_data.get("port_list", []))
            if err:
                raise ValueError(f"Invalid config for group '{groupname}': {err}")

    def _load_config(self):
        """Loads configuration from the json file."""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Could not load config from {self.config_path}: {e}")
            # Return a minimal default config to avoid crashing
            return {
                "listen": {"host": "127.0.0.1", "port": 25001},
                "lines": {}
            }

    def _save_config(self):
        """Saves the current in-memory configuration to the json file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logging.info(f"Configuration saved to {self.config_path}")
        except IOError as e:
            logging.error(f"Could not save config to {self.config_path}: {e}")

    async def start(self, host, port):
        """Start the server, including subprocesses and background tasks."""
        # Start the main TCP server
        self.server = await asyncio.start_server(self.handle_client, host, port)
        addrs = ", ".join(str(s.getsockname()) for s in self.server.sockets)
        logging.info(f"seriald listening on {addrs}")

        # Start ser2net instances
        await self._start_ser2net_instances()

        # Start background tasks
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        self._idle_timeout_task = asyncio.create_task(self._idle_timeout_loop())

        # Wait until shutdown is signaled
        await self._shutdown_event.wait()

    async def stop(self):
        """Gracefully stop the server, subprocesses, and background tasks."""
        if self._shutdown_event.is_set():
            return
        logging.info("Server shutting down...")

        # Stop ser2net instances first
        await self._stop_ser2net_instances()

        # Cancel helper tasks
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._idle_timeout_task:
            self._idle_timeout_task.cancel()

        # Close the main server
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        logging.info("Server has been shut down.")
        # Signal that shutdown is complete
        self._shutdown_event.set()

    async def _start_ser2net_instances(self):
        """Dynamically generate ser2net configs and launch them as subprocesses."""
        lines = (self.config or {}).get("lines", {})
        for line_id_str, line_cfg in lines.items():
            await self.start_ser2net_for_line(int(line_id_str))

    async def start_ser2net_for_line(self, line_id: int):
        """Start ser2net for a specific line."""
        line_id_str = str(line_id)
        lines = (self.config or {}).get("lines", {})
        line_cfg = lines.get(line_id_str)

        if not line_cfg:
            logging.error(f"No configuration found for line {line_id}")
            return

        try:
            if line_cfg.get("fakeserial") or not line_cfg.get("enabled", True):
                # Don't start ser2net for fake devices or disabled lines
                return

            ser2net_port = line_cfg.get("ser2net_port")
            device = line_cfg.get("device")

            # Construct the full baudrate/parity/etc. string for ser2net
            baud = line_cfg.get("baudrate", 115200)
            databits = line_cfg.get("databits", 8)
            parity_map = {"none": "n", "even": "e", "odd": "o", "mark": "m", "space": "s"}
            parity = parity_map.get(str(line_cfg.get("parity", "none")).lower(), "n")
            stopbits = line_cfg.get("stopbits", 1)
            flow = "xonxoff" if line_cfg.get("flowcontrol") == "xonxoff" else ""
            # Example: 115200n81,xonxoff
            baudrate_str = f"{baud}{parity}{databits}{stopbits}{flow}"

            if not all([ser2net_port, device]):
                logging.warning(f"Line {line_id}: missing ser2net_port or device, skipping.")
                return

            connector_str = f"serialdev,{device},{baudrate_str},local"
            max_clients = line_cfg.get("max_clients", 1)
            kickolduser = str(line_cfg.get("kickolduser", "false")).lower()

            config_content = (
                f"%YAML 1.1\n---\n"
                f"define: &banner \\r\\nser2net port \\p device \\d [\\B]\\r\\n\\r\\n\n"
                f"connection: &con{line_id}\n"
                f"  accepter: telnet,{ser2net_port}\n"
                f"  enable: on\n"
                f"  options:\n"
                f"    banner: *banner\n"
                f"    max-connections: {max_clients}\n"
                f"    kickolduser: {kickolduser}\n"
                f"  connector: {connector_str}\n"
            )

            temp_dir = "/tmp/seriald_ser2net_configs"
            os.makedirs(temp_dir, exist_ok=True)
            cfg_path = os.path.join(temp_dir, f"cs{line_id}.yaml")
            with open(cfg_path, "w") as f:
                f.write(config_content)

            cmd = ["sudo", "/usr/sbin/ser2net", "-c", cfg_path]
            logging.info(f"Starting ser2net for line {line_id} on port {ser2net_port}...")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.ser2net_processes[line_id] = process
            logging.info(f"ser2net for line {line_id} started with PID {process.pid}.")

        except (ValueError, KeyError, TypeError) as e:
            logging.error(f"Failed to process line {line_id}: {e}")
        except Exception as e:
            logging.error(f"Failed to start ser2net for line {line_id}: {e}")

    async def stop_ser2net_for_line(self, line_id: int):
        """Stop the ser2net process for a specific line."""
        # Also try to kill any orphaned process by config file path
        cfg_path = os.path.join("/tmp/seriald_ser2net_configs", f"cs{line_id}.yaml")
        try:
            # Use pkill to find and terminate the process using the specific config file.
            # This is more robust against orphaned processes.
            pkill_cmd = ["sudo", "pkill", "-f", f"ser2net -c {cfg_path}"]
            logging.info(f"Running command to clean up ser2net for line {line_id}: {' '.join(pkill_cmd)}")
            proc = await asyncio.create_subprocess_exec(*pkill_cmd)
            await proc.wait()
            # A non-zero return code is okay, it just means no process was found
        except Exception as e:
            logging.error(f"Failed to run pkill for line {line_id}: {e!r}")

        if line_id in self.ser2net_processes:
            process = self.ser2net_processes.pop(line_id)
            logging.info(f"Stopping ser2net for line {line_id} (PID {process.pid})...")
            try:
                # First, try a graceful shutdown
                process.terminate()
                try:
                    # Wait for a short timeout
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                    logging.info(f"ser2net for line {line_id} terminated gracefully.")
                    return
                except asyncio.TimeoutError:
                    # If it doesn't terminate, force kill it
                    logging.warning(f"ser2net for line {line_id} did not terminate gracefully, killing.")
                    process.kill()
                    await process.wait()
                    logging.info(f"ser2net for line {line_id} killed.")
            except ProcessLookupError:
                logging.warning(f"ser2net process for line {line_id} (PID {process.pid}) not found. It may have already exited.")
            except Exception as e:
                logging.error(f"Failed to stop ser2net for line {line_id}: {e!r}")
                # Ensure it's killed even on other errors
                try:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                except Exception as kill_e:
                    logging.error(f"Failed to force kill ser2net for line {line_id}: {kill_e}")

    async def _stop_ser2net_instances(self):
        """Terminate all managed ser2net subprocesses."""
        logging.info("Stopping all ser2net instances...")
        await asyncio.gather(*(self.stop_ser2net_for_line(line_id) for line_id in list(self.ser2net_processes.keys())))
        self.ser2net_processes.clear()

    async def _idle_timeout_loop(self):
        """Periodically check for idle clients and disconnect them if idle_timeout exceeded."""
        while True:
            await asyncio.sleep(5)
            now = time.time()
            for line_id, clients in list(self.clients_by_line.items()):
                line_cfg = self._line_cfg(line_id)
                idle_timeout = line_cfg.get("idle_timeout")
                if not idle_timeout:
                    continue
                try:
                    idle_timeout = int(idle_timeout)
                except Exception:
                    continue
                for c in list(clients):
                    last = self._last_activity.get(c)
                    if last is None:
                        # If no activity recorded, treat as just attached
                        self._last_activity[c] = now
                        continue
                    if now - last > idle_timeout:
                        # Disconnect idle client
                        try:
                            await self._send(c.writer, {"op": "detach", "reason": f"idle timeout ({idle_timeout}s)"})
                        except Exception:
                            pass
                        try:
                            c.writer.close()
                        except Exception:
                            pass
                        self.clients_by_line.get(line_id, set()).discard(c)
                        self._last_activity.pop(c, None)
                        # Remove from observer queue if present
                        try:
                            q = self._queue_for(line_id)
                            if c in q:
                                q.remove(c)
                        except Exception:
                            pass
                        if self.active_writer.get(line_id) is c:
                            self.active_writer.pop(line_id, None)
                            try:
                                asyncio.create_task(self._maybe_promote_writer(line_id))
                            except Exception:
                                pass

    def _queue_for(self, line: int) -> deque:
        # Get the observer queue (FIFO) for a given line.
        q = self.observer_queue.get(line)
        if q is None:
            # If it doesn't exist, create a new deque and store it.
            q = deque()
            self.observer_queue[line] = q
        # Return the queue for this line.
        return q

    async def _maybe_promote_writer(self, line: int):
        """Promote the oldest observer (if any) to writer in exclusive mode."""
        if self._line_cfg(line).get("mode") != "exclusive":
            return
        if line in self.active_writer and self.active_writer[line] is not None:
            return
        q = self._queue_for(line)
        while q:
            candidate = q.popleft()
            # ensure candidate is still attached
            if candidate in self.clients_by_line.get(line, set()):
                self.active_writer[line] = candidate
                candidate.can_write = True
                try:
                    await self._send(candidate.writer, {"op": "role", "role": "writer", "line": line, "reason": "promote"})
                except Exception:
                    # if we can't notify candidate, drop and continue
                    self.clients_by_line.get(line, set()).discard(candidate)
                    self.active_writer.pop(line, None)
                    continue
                break

    def _line_cfg(self, line: int) -> dict:
        lines = (self.config or {}).get("lines", {})
        # Default config now uses max_clients instead of max_observers
        return lines.get(str(line), {"mode": "exclusive", "echo": True, "window_ms": 800, "max_clients": None})

    def _ensure_backend(self, line: int):
        # Ensure a backend (real or fake) exists for the given line.
        if line not in self.backends:
            cfg = self._line_cfg(line)
            # In the new architecture, server only manages FakeSerialDevice for testing.
            # Real devices are handled by clients connecting directly to ser2net.
            if cfg.get("fakeserial"):
                self.backends[line] = FakeSerialDevice()
            else:
                # For non-fake lines, there is no backend on the server.
                # We can use a placeholder if needed, but for now, None is fine.
                self.backends[line] = None

        backend = self.backends.get(line)
        if backend:
            # Start the backend (spawns its background thread for serial I/O)
            backend.start()
            # If not already running, start the async receive loop for this line.
            # This task will continuously read from the backend and forward data to all clients on this line.
            if line not in self._rx_tasks:
                self._rx_tasks[line] = asyncio.create_task(self._serial_rx_loop(line))

    async def _serial_rx_loop(self, line: int):
        backend = self.backends.get(line)
        # This loop should only run for backends that exist (i.e., FakeSerialDevice)
        if not backend:
            return
        while True:
            data = backend.recv(timeout=0.2)
            if not data:
                await asyncio.sleep(0.05)
                continue
            payload = json.dumps({
                "op": "serial",
                "line": line,
                "data": base64.b64encode(data).decode(),
            }).encode() + b"\n"
            for c in list(self.clients_by_line.get(line, set())):
                try:
                    c.writer.write(payload)
                    await c.writer.drain()
                except Exception:
                    # drop broken clients
                    self.clients_by_line.get(line, set()).discard(c)
                    if self.active_writer.get(line) is c:
                        self.active_writer.pop(line, None)
                        # best-effort promotion when writer drops
                        try:
                            asyncio.create_task(self._maybe_promote_writer(line))
                        except Exception:
                            pass

    async def _keepalive_loop(self):
        """Periodically send a lightweight ping to clients to prune broken connections."""
        while True:
            await asyncio.sleep(self.keepalive_interval)
            try:
                for line_id, clients in list(self.clients_by_line.items()):
                    for c in list(clients):
                        try:
                            await self._send(c.writer, {"op": "ping", "line": line_id, "ts": time.time()})
                        except Exception:
                            # drop broken client and repair writer/queue state
                            clients.discard(c)
                            # remove from observer queue if present
                            try:
                                q = self._queue_for(line_id)
                                if c in q:
                                    q.remove(c)
                            except Exception:
                                pass
                            if self.active_writer.get(line_id) is c:
                                self.active_writer.pop(line_id, None)
                                try:
                                    asyncio.create_task(self._maybe_promote_writer(line_id))
                                except Exception:
                                    pass
                    # reset line state when fully detached
                    if not clients:
                        # If there are no clients left on this line, fully reset line state:
                        try:
                            # Remove any active writer reference for this line
                            self.active_writer.pop(line_id, None)
                        except Exception:
                            pass
                        try:
                            # Remove any micro-lock for this line (shared mode)
                            self.line_lock.pop(line_id, None)
                        except Exception:
                            pass
                        try:
                            # Clear the observer queue for this line (exclusive mode)
                            q = self._queue_for(line_id)
                            q.clear()
                        except Exception:
                            pass
            except Exception:
                # keepalive should be robust; continue on errors
                continue

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        ip, port = None, None
        if peer:
            ip, port = peer[0], peer[1]

        client_id = f"{ip}:{port}"
        logging.debug(f"Connection opened from {client_id}")

        client = Client(writer=writer, ip=ip, port=port)
        now = time.time()
        self._last_activity[client] = now
        # If Session object is used, pass IP/port when creating
        # Example: session = Session(user, role, ip=ip, port=port)
        try:
            # Main loop: process incoming lines from the client
            while True:
                # logging.debug("Waiting for client message...")
                line = await reader.readline()
                now = time.time()
                if not line:
                    # Client disconnected
                    logging.debug(f"Client {client_id} sent empty line, closing connection.")
                    break
                self._last_activity[client] = now
                try:
                    # Parse JSON message from client
                    msg = json.loads(line.decode())
                    logging.debug(f"Received from {client_id}: {msg}")
                except Exception:
                    # Send error if JSON is invalid, then continue
                    await self._send(writer, {"op": "error", "msg": "invalid json"})
                    continue
                op = msg.get("op")
                # Handle 'activity' op (client heartbeat)
                if op == "activity":
                    # The timestamp has already been updated, so we just continue.
                    # The activity op can be used by clients to keep the connection alive and prevent idle timeouts.
                    continue

                # Handle 'config' and 'startup-config' operations
                if op in ["config", "startup-config"]:
                    config_source = self.config if op == "config" else self._load_config()

                    line_id_or_label = msg.get("line")
                    if isinstance(line_id_or_label, str):
                        line_id_or_label = line_id_or_label.strip()
                    show_groups = msg.get("groups")
                    show_users = msg.get("users")

                    response_config = {}

                    if line_id_or_label:
                        if isinstance(line_id_or_label, str) and line_id_or_label.lower() == "all":
                            response_config = {"lines": dict(config_source.get("lines", {}))}
                        else:
                            found_line = None
                            line_key = str(line_id_or_label)
                            # Try to match by line ID (number)
                            if line_key in config_source.get("lines", {}):
                                found_line = {line_key: config_source["lines"][line_key]}
                            else:
                                # Try to match by label
                                for line_id, line_data in config_source.get("lines", {}).items():
                                    if line_data.get("label") == line_id_or_label:
                                        found_line = {line_id: line_data}
                                        break
                            response_config = {"lines": found_line} if found_line else {"lines": {}}
                    elif show_groups:
                        response_config = {"groups": config_source.get("groups", {})}
                    elif show_users:
                        response_config = {"users": config_source.get("users", {})}
                    else:
                        # Return the full (but safe) configuration
                        response_config = dict(config_source)

                    await self._send(writer, {"op": op, "config": response_config})
                    continue

                # Handle 'product-info' operation
                if op == "product-info":
                    config_source = self.config
                    info_data = config_source.get("info", {})
                    await self._send(writer, {"op": "product-info", "data": info_data})
                    continue

                # Handle 'attach' operation: client requests to attach to a line
                if op == "attach":
                    line_id = int(msg.get("line", 1))
                    mode = msg.get("mode", "writer")
                    username = msg.get("user")
                    # Use client_ip/client_port from message if present (workaround for SSH forced command)
                    msg_ip = msg.get("client_ip")
                    msg_port = msg.get("client_port")
                    if msg_ip:
                        client.ip = msg_ip
                    if msg_port:
                        try:
                            client.port = int(msg_port)
                        except Exception:
                            client.port = msg_port
                    client.user = username
                    client.line_id = line_id
                    # RBAC: check if user is allowed to access this port
                    users = self.config.get("users", {})
                    groups = self.config.get("groups", {})
                    user_entry = users.get(username)
                    allowed = False
                    if user_entry:
                        user_groups = user_entry.get("groups", [])
                        for gname in user_groups:
                            group = groups.get(gname)
                            if group and line_id in group.get("port_list", []):
                                allowed = True
                                break
                    if not allowed:
                        await self._send(writer, {"op": "error", "msg": f"access denied to port {line_id}"})
                        return
                    line_cfg = self._line_cfg(line_id)
                    # Enforce max_clients if set (total clients: writer + observers)
                    max_clients = line_cfg.get("max_clients")
                    clients_set = self.clients_by_line.setdefault(line_id, set())
                    n_clients = len(clients_set)
                    if max_clients is not None and max_clients is not False:
                        try:
                            maxc = int(max_clients)
                        except Exception:
                            maxc = None
                        if maxc is None:
                            await self._send(writer, {"op": "error", "msg": "invalid max_clients value"})
                            return
                        if maxc < 1 or maxc > 4:
                            await self._send(writer, {"op": "error", "msg": "max_clients must be between 1 and 4"})
                            return
                        if n_clients >= maxc:
                            await self._send(writer, {"op": "error", "msg": f"client limit reached ({maxc})"})
                            return
                    # Add client to the set for this line
                    logging.debug(f"{line_id} Client attaching")
                    clients_set.add(client)
                    # Only ensure backend if this line uses fakeserial
                    if line_cfg.get("fakeserial"):
                        logging.debug(f"{line_id} Ensuring backend for line (fakeserial)")
                        self._ensure_backend(line_id)

                    can_write = False
                    if line_cfg.get("mode") == "exclusive":
                        # Exclusive mode: only one writer allowed
                        if mode == "writer" and line_id not in self.active_writer:
                            self.active_writer[line_id] = client
                            can_write = True
                        else:
                            # Queue observers for future promotion
                            q = self._queue_for(line_id)
                            q.append(client)
                    else:  # shared mode: allow write attempts, but gate via micro-lock
                        can_write = True
                    client.can_write = can_write

                    # --- New Architecture: Send ser2net info to client ---
                    ser2net_host = line_cfg.get("ser2net_host")
                    ser2net_port = line_cfg.get("ser2net_port")
                    fakeserial = line_cfg.get("fakeserial", False)

                    # Notify client of attach result and role
                    await self._send(writer, {
                        "op": "attach",
                        "ok": True,
                        "role": "writer" if can_write else "observer",
                        "line": line_id,
                        "mode": line_cfg.get("mode", "exclusive"),
                        "fakeserial": fakeserial,
                        "ser2net_host": ser2net_host,
                        "ser2net_port": ser2net_port,
                    })
                # Handle 'status' operation: client requests status snapshot
                elif op == "status":
                    line_filter = msg.get("line")
                    try:
                        line_filter = int(line_filter) if line_filter is not None else None
                    except (ValueError, TypeError):
                        line_filter = None

                    # Build a snapshot of all lines and clients
                    lines: dict[int, dict] = {}
                    # Determine which lines to iterate over
                    if line_filter is not None:
                        lines_to_process = [line_filter]
                    else:
                        lines_to_process = (self.config or {}).get("lines", {}).keys()

                    # Include any configured lines even if empty
                    for k in lines_to_process:
                        try:
                            lines[int(k)] = {"mode": self._line_cfg(int(k)).get("mode", "exclusive"), "clients": []}
                        except Exception:
                            continue
                    # Include any active lines
                    for line_id, clients in self.clients_by_line.items():
                        if line_filter is not None and line_id != line_filter:
                            continue
                        if line_id not in lines:
                            lines[line_id] = {"mode": self._line_cfg(line_id).get("mode", "exclusive"), "clients": []}
                        line_cfg = self._line_cfg(line_id)
                        idle_timeout = line_cfg.get("idle_timeout")
                        try:
                            idle_timeout = int(idle_timeout) if idle_timeout is not None else None
                        except Exception:
                            idle_timeout = None
                        now = time.time()
                        for c in list(clients):
                            role = "writer" if self.active_writer.get(line_id) is c or c.can_write else "observer"
                            last_activity = self._last_activity.get(c)
                            if idle_timeout is not None and last_activity is not None:
                                time_left = max(0, idle_timeout - int(now - last_activity))
                            else:
                                time_left = None
                            lines[line_id].setdefault("clients", []).append({
                                "user": c.user or "unknown",
                                "role": role,
                                "ip": c.ip,
                                "port": c.port,
                                "idle_timeout": idle_timeout,
                                "last_activity": last_activity,
                                "time_left": time_left,
                            })
                    # Prepare output summary for all lines
                    out = []
                    sorted_keys = sorted(lines.keys())
                    if line_filter is not None and line_filter not in sorted_keys:
                        # If filtering and the line has no config and no active clients, it won't be in `lines`.
                        # Add a minimal entry for it.
                        sorted_keys.append(line_filter)

                    for line_id in sorted_keys:
                        if line_filter is not None and line_id != line_filter:
                            continue
                        entry = lines.get(line_id)
                        if not entry: # Handle case where filtered line has no info
                            entry = {"mode": self._line_cfg(line_id).get("mode", "exclusive"), "clients": []}

                        writer_client = self.active_writer.get(line_id)
                        writer_user = None
                        if writer_client is not None:
                            writer_user = writer_client.user or "unknown"
                        # Count writers and observers
                        clients = entry.get("clients", [])
                        n_obs = sum(1 for it in clients if it.get("role") != "writer")
                        n_wri = sum(1 for it in clients if it.get("role") == "writer")
                        out.append({
                            "line": line_id,
                            "mode": entry.get("mode"),
                            "writer": writer_user,
                            "counts": {"clients": len(clients), "writers": n_wri, "observers": n_obs},
                            "clients": clients,
                        })
                    # Send status response
                    await self._send(writer, {"op": "status", "lines": out})
                # Handle 'override' operation: forcibly become writer
                elif op == "override":
                    line_id = client.line_id
                    if line_id is None:
                        await self._send(writer, {"op": "error", "msg": "not attached"})
                    else:
                        # Demote previous writer if present
                        prev = self.active_writer.get(line_id)
                        self.active_writer[line_id] = client
                        client.can_write = True
                        if prev and prev is not client:
                            prev.can_write = False
                            # Put previous writer at head of queue to be next
                            q = self._queue_for(line_id)
                            try:
                                q.appendleft(prev)
                            except Exception:
                                pass
                        # Notify client of override
                        await self._send(writer, {"op": "override", "ok": True})

                # Handle 'config_port' operation
                elif op == "config_port":
                    line_id = msg.get("line")
                    if line_id is None:
                        await self._send(writer, {"op": "error", "msg": "missing line id"})
                        continue

                    line_id_str = str(line_id)
                    if line_id_str not in self.config["lines"]:
                        await self._send(writer, {"op": "error", "msg": f"line {line_id} not found"})
                        continue

                    line_cfg = self.config["lines"][line_id_str]

                    updated = False
                    for key in ["baudrate", "databits", "parity", "stopbits", "flowcontrol"]:
                        if key in msg:
                            line_cfg[key] = msg[key]
                            updated = True

                    if updated:
                        # self._save_config() # Removed to separate running-config from startup-config
                        await self.stop_ser2net_for_line(int(line_id))
                        await asyncio.sleep(0.5) # Give OS time to release the port
                        await self.start_ser2net_for_line(int(line_id))
                        await self._send(writer, {"op": "config_port", "ok": True, "line": line_id})
                    else:
                        #await self._send(writer, {"op": "config_port", "ok": False, "line": line_id, "msg": "no valid parameters to update"})
                        await self._send(writer, {"op": "config_port", "ok": True, "line": line_id})
                    continue

                # Handle 'config_op' operation
                elif op == "config_op":
                    line_id = msg.get("line")
                    if line_id is None:
                        await self._send(writer, {"op": "error", "msg": "missing line id"})
                        continue

                    line_id_str = str(line_id)
                    if line_id_str not in self.config["lines"]:
                        await self._send(writer, {"op": "error", "msg": f"line {line_id} not found"})
                        continue

                    if "max_clients" in msg:
                        try:
                            maxc = int(msg["max_clients"])
                        except Exception:
                            await self._send(writer, {"op": "error", "msg": "max_clients must be an integer between 1 and 4"})
                            continue
                        if maxc < 1 or maxc > 4:
                            await self._send(writer, {"op": "error", "msg": "max_clients must be between 1 and 4"})
                            continue
                        msg["max_clients"] = maxc

                    if "label" in msg:
                        label_error = validate_label(msg["label"])
                        if label_error:
                            await self._send(writer, {"op": "error", "msg": label_error})
                            continue

                    line_cfg = self.config["lines"][line_id_str]

                    restart_required = False
                    updated = False
                    for key in ["mode", "max_clients", "idle_timeout", "label"]:
                        if key in msg:
                            if line_cfg.get(key) != msg[key]:
                                line_cfg[key] = msg[key]
                                updated = True
                                if key in ["mode", "max_clients"]:
                                    restart_required = True

                    if updated:
                        # self._save_config() # Removed to separate running-config from startup-config
                        if restart_required:
                            logging.info(f"Restarting ser2net for line {line_id} due to config change.")
                            # Mode changes might require ser2net restart if kickolduser or max-connections changes
                            await self.stop_ser2net_for_line(int(line_id))
                            await asyncio.sleep(0.5) # Give OS time to release the port
                            await self.start_ser2net_for_line(int(line_id))
                        else:
                            logging.info(f"Updated config for line {line_id} without restart.")

                        await self._send(writer, {"op": "config_op", "ok": True, "line": line_id})
                    else:
                        # await self._send(writer, {"op": "config_op", "ok": False, "line": line_id, "msg": "no valid parameters to update or "})
                        await self._send(writer, {"op": "config_op", "ok": True, "line": line_id})
                    continue

                # Handle 'save-config' operation
                elif op == "save-config":
                    try:
                        self._save_config()
                        await self._send(writer, {"op": "save-config", "ok": True})
                    except Exception as e:
                        await self._send(writer, {"op": "save-config", "ok": False, "msg": str(e)})
                    continue

                # Handle 'config_user'
                elif op == "config_user":
                    username = msg.get("username")
                    if not username:
                        await self._send(writer, {"op": "error", "msg": "missing username"})
                        continue

                    username_error = validate_username(username)
                    if username_error:
                        await self._send(writer, {"op": "error", "msg": username_error})
                        continue

                    password = msg.get("password")
                    if password is not None:
                        password_error = validate_password(password)
                        if password_error:
                            await self._send(writer, {"op": "error", "msg": password_error})
                            continue

                    # Check if we are adding a new user and if the limit is reached
                    if username not in self.users and len(self.users) >= self.user_limit:
                        await self._send(writer, {"op": "error", "msg": f"User limit of {self.user_limit} reached"})
                        continue

                    users = self.config.setdefault("users", {})
                    is_new_user = username not in users
                    # Require password only for new users
                    if is_new_user and "password" not in msg:
                        await self._send(writer, {"op": "error", "msg": "missing password for new user"})
                        continue

                    user_data = users.setdefault(username, {
                        "role": USER_DEFAULT_ROLE,
                        "groups": USER_DEFAULT_GROUP
                    })

                    # If the user already existed, these keys might be missing.
                    # Ensure they have default values if not provided in the command.
                    if "role" not in user_data:
                        user_data['role'] = USER_DEFAULT_ROLE
                    if "groups" not in user_data:
                        user_data['groups'] = USER_DEFAULT_GROUP

                    # Now, apply any values that were actually passed in the command
                    if "role" in msg:
                        user_data["role"] = msg["role"]
                    if "groups" in msg:
                        user_data["groups"] = msg["groups"]
                    if password is not None:
                        user_data["password"] = password

                    await self._send(writer, {"op": "config_user", "ok": True, "username": username})
                    continue

                # Handle 'config_no_user'
                elif op == "config_no_user":
                    username = msg.get("username")
                    if not username:
                        await self._send(writer, {"op": "error", "msg": "missing username"})
                        continue

                    if username in self.config.get("users", {}):
                        del self.config["users"][username]
                        await self._send(writer, {"op": "config_no_user", "ok": True, "username": username})
                    else:
                        await self._send(writer, {"op": "error", "msg": f"user {username} not found"})
                    continue

                # Handle 'config_group'
                elif op == "config_group":
                    groupname = msg.get("groupname")
                    groupname_error = validate_groupname(groupname)
                    if groupname_error:
                        await self._send(writer, {"op": "error", "msg": groupname_error})
                        continue

                    # Check if we are adding a new group and if the limit is reached
                    if groupname not in self.groups and len(self.groups) >= self.group_limit:
                        await self._send(writer, {"op": "error", "msg": f"Group limit of {self.group_limit} reached"})
                        continue

                    groups = self.config.setdefault("groups", {})
                    # Use setdefault to create the group with defaults if it doesn't exist
                    group_data = groups.setdefault(groupname, {
                        "role": GROUP_DEFAULT_ROLE,
                        "port_list": GROUP_DEFAULT_PORTS
                    })

                    # If the group already existed, these keys might be missing.
                    # Ensure they have default values if not provided in the command.
                    if "role" not in group_data:
                        group_data['role'] = GROUP_DEFAULT_ROLE
                    if "port_list" not in group_data:
                        group_data['port_list'] = GROUP_DEFAULT_PORTS

                    # Now, apply any values that were actually passed in the command
                    if "ports" in msg:
                        port_list_error = self._validate_group_port_list(msg["ports"])
                        if port_list_error:
                            await self._send(writer, {"op": "error", "msg": port_list_error})
                            continue
                        group_data["port_list"] = msg["ports"]
                    if "role" in msg:
                        group_data["role"] = msg["role"]

                    await self._send(writer, {"op": "config_group", "ok": True, "groupname": groupname})
                    continue

                # Handle 'config_no_group'
                elif op == "config_no_group":
                    groupname = msg.get("groupname")
                    groupname_error = validate_groupname(groupname)
                    if groupname_error:
                        await self._send(writer, {"op": "error", "msg": groupname_error})
                        continue

                    if groupname in self.config.get("groups", {}):
                        del self.config["groups"][groupname]
                        # Also remove this group from any users who are members
                        for username, user_data in self.config.get("users", {}).items():
                            if groupname in user_data.get("groups", []):
                                user_data["groups"].remove(groupname)
                        await self._send(writer, {"op": "config_no_group", "ok": True, "groupname": groupname})
                    else:
                        await self._send(writer, {"op": "error", "msg": f"group {groupname} not found"})
                    continue

                # Handle 'input' operation: client sends input data
                elif op == "input":
                    line_id = client.line_id
                    if line_id is None:
                        await self._send(writer, {"op": "error", "msg": "not attached"})
                        continue
                    data_b64 = msg.get("data", "")
                    now = time.time()
                    self._last_activity[client] = now
                    try:
                        # Decode base64 input data
                        data = base64.b64decode(data_b64)
                    except Exception:
                        await self._send(writer, {"op": "error", "msg": "bad data"})
                        continue
                    line_cfg = self._line_cfg(line_id)
                    if line_cfg.get("mode") == "exclusive":
                        # Only writer can send input
                        if self.active_writer.get(line_id) is client:
                            # In exclusive mode, the server is responsible for echo.
                            # Only fakeserial data is handled by the server.
                            if line_cfg.get("fakeserial"):
                                self.backends[line_id].send(data)

                            # Echo to all clients, including the writer.
                            if line_cfg.get("echo", True):
                                for c in list(self.clients_by_line.get(line_id, set())):
                                    try:
                                        await self._send(c.writer, {
                                            "op": "echo",
                                            "line": line_id,
                                            "data": data_b64,
                                        })
                                    except Exception:
                                        self.clients_by_line.get(line_id, set()).discard(c)
                        else:
                            await self._send(writer, {"op": "error", "msg": "not writer"})
                    else:  # shared mode
                        # In shared mode, the client sends to the data plane, and the device's
                        # own echo is what all clients see. The server's only job is to
                        # handle the fakeserial case where there is no separate data plane.
                        if line_cfg.get("fakeserial"):
                            self.backends[line_id].send(data)
                            # For fakeserial, we must also manually echo to all clients.
                            for c in list(self.clients_by_line.get(line_id, set())):
                                try:
                                    await self._send(c.writer, {
                                        "op": "echo",
                                        "line": line_id,
                                        "data": data_b64,
                                    })
                                except Exception:
                                    self.clients_by_line.get(line_id, set()).discard(c)
                # Handle 'detach' operation: client detaches from line
                elif op == "detach":
                    line_id = client.line_id
                    if line_id is not None:
                        # Remove client from all tracking structures
                        self.clients_by_line.get(line_id, set()).discard(client)
                        # Remove from observer queue if present
                        try:
                            q = self._queue_for(line_id)
                            # deque remove is O(n), acceptable for small queues
                            if client in q:
                                q.remove(client)
                        except Exception:
                            pass
                        # If client was writer, promote next observer
                        if self.active_writer.get(line_id) is client:
                            self.active_writer.pop(line_id, None)
                            await self._maybe_promote_writer(line_id)
                        client.line_id = None
                        client.can_write = False
                        # Notify client of detach
                        await self._send(writer, {"op": "detach", "ok": True})
                # Handle unknown operation
                else:
                    await self._send(writer, {"op": "error", "msg": "unknown op"})
        finally:
            # Remove from last activity tracking
            self._last_activity.pop(client, None)
            # Cleanup: always run on disconnect or error
            logging.debug(f"Connection closed from {client_id}")
            line_id = client.line_id
            if line_id is not None:
                # Remove client from all tracking structures
                self.clients_by_line.get(line_id, set()).discard(client)
                # Remove from observer queue if present
                try:
                    q = self._queue_for(line_id)
                    if client in q:
                        q.remove(client)
                except Exception:
                    pass
                # Clear writer reference if it belonged to the disconnecting client
                if self.active_writer.get(line_id) is client:
                    self.active_writer.pop(line_id, None)
                    # Schedule promotion; cannot await in finally directly if writer.close() below
                    try:
                        asyncio.create_task(self._maybe_promote_writer(line_id))
                    except Exception:
                        pass
                # If the line now has no clients, fully reset line state to avoid stale roles
                if not self.clients_by_line.get(line_id):
                    try:
                        self.active_writer.pop(line_id, None)
                    except Exception:
                        pass
                    try:
                        self.line_lock.pop(line_id, None)
                    except Exception:
                        pass
                    try:
                        q = self._queue_for(line_id)
                        q.clear()
                    except Exception:
                        pass
            try:
                # Close the writer and wait for it to close
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send(self, w: asyncio.StreamWriter, obj: dict):
        w.write(json.dumps(obj).encode() + b"\n")
        await w.drain()

async def main(host="127.0.0.1", port=25001, config_path: Optional[str] = None):
    config_path = config_path or os.path.join(os.path.dirname(__file__), "config.json")

    cfg = None
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
    except Exception as e:
        logging.error(f"failed to load config: {e}")
        cfg = None

    daemon = SerialDaemon(config=cfg, config_path=config_path)

    # If config provides listen host/port, prefer them unless args override
    listen = (cfg or {}).get("listen", {})
    host = host or listen.get("host", "127.0.0.1")
    port = port or int(listen.get("port", 25001))

    # Set up signal handlers
    loop = asyncio.get_running_loop()

    def signal_handler():
        # This function will be wrapped in a lambda to schedule the stop coroutine
        logging.info("Signal received, initiating shutdown...")
        asyncio.create_task(daemon.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await daemon.start(host, port)
    except asyncio.CancelledError:
        # This is expected on shutdown
        pass

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="seriald daemon")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--config", default=None)
    args = p.parse_args()

    try:
        asyncio.run(main(args.host, args.port, args.config))
    except KeyboardInterrupt:
        # This is now primarily handled by the signal handler, but kept as a fallback.
        logging.info("KeyboardInterrupt caught, shutting down.")


