"""Lutron Telnet communication handler."""
import asyncio
import enum
import logging
import re
from dataclasses import dataclass
from typing import Optional

try:
    from homeassistant.exceptions import HomeAssistantError
except ImportError:  # standalone use from scripts/, without Home Assistant installed
    HomeAssistantError = Exception

_LOGGER = logging.getLogger(__name__)

# Telnet defaults
DEFAULT_TELNET_PORT = 23

# Keep-alive
PING_INTERVAL = 60         # seconds of silence from the hub before a keep-alive ping

# Reconnect backoff between failed connection attempts
RECONNECT_MIN_DELAY = 5    # seconds before the first retry
RECONNECT_MAX_DELAY = 300  # cap for exponential backoff

# Command retry after a lost reply
COMMAND_ATTEMPTS = 2       # total sends per command, including the first
RECONNECT_WAIT = 15        # seconds a retry waits for the connection to come back

# Auth handshake timing
LOGIN_TIMEOUT = 5.0        # seconds to wait for each login prompt
READ_CHUNK_SIZE = 256      # bytes per read chunk in _expect

# Command I/O timing
READ_LINE_TIMEOUT = 0.5    # per-line read timeout in _reader_loop
REPLY_TIMEOUT = 5.0        # seconds to wait for the hub to answer a command

# Zone discovery
DEFAULT_MAX_ZONES = 100
DISCOVERY_ZONE_DELAY = 0.1  # seconds between zone queries to avoid flooding the hub

# Lutron Integration Protocol — OUTPUT action IDs
# Used in #OUTPUT,<zone>,<action>[,<params>] and ?OUTPUT,<zone>,<action>
#
# Action | Supports  | Name                            | Parameters
# -------+-----------+---------------------------------+-------------------------------------
#   1    | Set, Get  | Zone Level                      | level (0–100), fade (s), delay (s)
#   2    | Set       | Start Raising                   | —
#   3    | Set       | Start Lowering                  | —
#   4    | Set       | Stop Raising or Lowering        | —
#   5    | Set       | Start Flashing                  | fade (s)
#   6    | Set       | Pulse Time                      | fade (s)
#   9    | Set, Get  | Tilt Level                      | tilt (0–100), fade (s), delay (s)
#  10    | Set, Get  | Lift & Tilt Level               | lift (0–100), tilt (0–100), fade, delay
#  11    | Set       | Start Raising Tilt              | —
#  12    | Set       | Start Lowering Tilt             | —
#  13    | Set       | Stop Raising or Lowering Tilt   | —
#  14    | Set       | Start Raising Lift              | —
#  15    | Set       | Start Lowering Lift             | —
#  16    | Set       | Stop Raising or Lowering Lift   | —
#  17    | Set       | DMX Color or Level              | color/level index (0–255 / 0.00–100.00)
#  18    | Set       | Motor Jog Raise                 | —
#  19    | Set       | Motor Jog Lower                 | —
#  20    | Set       | Motor 4-Stage Jog Raise         | —
#  21    | Set       | Motor 4-Stage Jog Lower         | —
#
# Notes:
#   Actions 9–16 not supported in Quantum
#   Actions 11–16 not supported in Athena
#   Action 17 not supported in RadioRA 2
#   Action numbers 7 and 8 are not OUTPUT actions
OUTPUT_ACTION_ZONE_LEVEL = 1

# Lutron Integration Protocol — ~ERROR,<code> reply codes
#   1 Parameter count mismatch   4 Parameter data out of range
#   2 Object does not exist      5 Parameter data malformed
#   3 Invalid action number      6 Unsupported command
ERROR_OBJECT_DOES_NOT_EXIST = 2

# Push event source tags
SOURCE_INTERNAL = "internal"  # ~OUTPUT echoed back from a command we sent
SOURCE_EXTERNAL = "external"  # unsolicited push from Pico, app, or another system


class LutronError(HomeAssistantError):
    """Base class for Lutron hub command failures."""


class NotConnected(LutronError):
    """The hub connection is not up (or did not come back in time)."""


class NoReply(LutronError):
    """The hub did not answer a command: reply timeout or socket error."""


class HubError(LutronError):
    """The hub answered a command with ~ERROR; the link itself is fine."""

    def __init__(self, command: str, response: str) -> None:
        # "~ERROR,2" per the LIP spec; Caseta sends "~ERROR,Enum=(2, 0x00000002)"
        match = re.match(r"~ERROR,\D*(\d+)", response)
        self.code: Optional[int] = int(match.group(1)) if match else None
        super().__init__(f"Lutron hub rejected '{command}': {response}")


class ConnState(enum.Enum):
    """Connection manager states."""

    DISCONNECTED = "disconnected"  # not started, or stopped on purpose
    CONNECTING = "connecting"      # logging in, or waiting out backoff before the next try
    CONNECTED = "connected"        # logged in; reader and keep-alive running


_ALLOWED_TRANSITIONS = {
    ConnState.DISCONNECTED: {ConnState.CONNECTING},
    ConnState.CONNECTING: {ConnState.CONNECTED, ConnState.DISCONNECTED},
    ConnState.CONNECTED: {ConnState.CONNECTING, ConnState.DISCONNECTED},
}


@dataclass
class _PendingReply:
    """The one command waiting for a reply. Only _send_once creates or clears it."""

    zone: Optional[int]  # only an ~OUTPUT for this zone answers; None accepts any
    future: asyncio.Future

    def matches(self, line: str) -> bool:
        """Return True if `line` answers this command."""
        if self.future.done():
            return False
        if line.startswith("~ERROR"):
            return True
        if not line.startswith("~OUTPUT"):
            return False
        if self.zone is None:
            return True
        parts = line.split(",")
        return len(parts) > 1 and parts[1].strip() == str(self.zone)


class LutronTelnetConnection:
    """Manages the Telnet connection to a Lutron Caseta Pro hub.

    The connection is a three-state machine (see ConnState). Only connect(),
    disconnect() and the connection loop open or close the socket; every state
    change goes through _transition().

    Invariant: while CONNECTED, the socket, the reader task and the keep-alive
    task all exist; outside CONNECTED none of them do. _transition() is the only
    place they are created or destroyed, so checking _state is enough.

    One command is in flight at a time (_command_lock): hub replies carry no
    request ID, so this is what keeps replies matched to their commands.
    """

    def __init__(self, host: str, port: int = DEFAULT_TELNET_PORT, username: str = "lutron", password: str = "integration", ping_zone: int = 1):
        """Initialize the Telnet connection.

        Args:
            host: IP address of the Lutron hub (e.g., "10.0.1.111")
            port: Telnet port (default: 23)
            username: Telnet username (default: "lutron")
            password: Telnet password (default: "integration")
            ping_zone: Zone ID to use for keep-alive pings (default: 1)
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ping_zone = ping_zone
        self._state = ConnState.DISCONNECTED
        self._connected_event = asyncio.Event()  # set exactly while CONNECTED
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._last_activity = 0.0  # loop time of the last line received from the hub
        self._connection_task: Optional[asyncio.Task] = None  # owns every login attempt
        self._first_attempt: Optional[asyncio.Future] = None  # what connect() awaits
        self._pending: Optional[_PendingReply] = None  # None while no command awaits a reply
        self._push_callbacks: list = []
        self._availability_callbacks: list = []
        self._command_lock = asyncio.Lock()  # Serialize command/response cycles

    def add_push_callback(self, callback) -> None:
        """Register a callback for push events from the hub."""
        self._push_callbacks.append(callback)

    def remove_push_callback(self, callback) -> None:
        """Unregister a push event callback."""
        self._push_callbacks.remove(callback)

    def add_availability_callback(self, callback) -> None:
        """Register a callback invoked with True/False when availability changes."""
        self._availability_callbacks.append(callback)

    def remove_availability_callback(self, callback) -> None:
        """Unregister an availability callback."""
        self._availability_callbacks.remove(callback)

    @property
    def state(self) -> ConnState:
        """Return the connection state."""
        return self._state

    @property
    def available(self) -> bool:
        """Return True while connected to the hub."""
        return self._state is ConnState.CONNECTED

    @property
    def is_connected(self) -> bool:
        """Return whether we're connected to the hub."""
        return self._state is ConnState.CONNECTED

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, new: ConnState, reason: str) -> None:
        """Move to `new` and run its side effects. Raises on an illegal transition."""
        old = self._state
        if new not in _ALLOWED_TRANSITIONS[old]:
            raise RuntimeError(f"Illegal connection transition {old.name} -> {new.name} ({reason})")

        _LOGGER.debug("Connection %s -> %s: %s", old.name, new.name, reason)
        self._state = new

        if old is ConnState.CONNECTED:
            self._teardown()
            self._connected_event.clear()

        if new is ConnState.CONNECTED:
            self._start_background_tasks()
            self._connected_event.set()
        elif new is ConnState.CONNECTING:
            # A first connect tries at once; after a loss, back off before retrying
            delay = 0 if old is ConnState.DISCONNECTED else RECONNECT_MIN_DELAY
            self._connection_task = asyncio.create_task(self._connection_loop(delay))
        elif new is ConnState.DISCONNECTED:
            if self._connection_task and self._connection_task is not asyncio.current_task():
                self._connection_task.cancel()
            self._connection_task = None
            self._teardown()

        if (old is ConnState.CONNECTED) != (new is ConnState.CONNECTED):
            self._notify_availability(new is ConnState.CONNECTED)

    def _notify_availability(self, available: bool) -> None:
        """Tell availability callbacks the connection went up or down."""
        for callback in list(self._availability_callbacks):
            try:
                callback(available)
            except Exception as e:
                _LOGGER.error("Availability callback error: %s", e)

    def _on_connection_lost(self, reason: str) -> None:
        """Report a dead link. No-op unless CONNECTED, so repeat reports are harmless."""
        if self._state is not ConnState.CONNECTED:
            return
        _LOGGER.warning("Lost connection to Lutron hub at %s: %s", self.host, reason)
        self._transition(ConnState.CONNECTING, reason)

    def _start_background_tasks(self) -> None:
        """Start the reader and keep-alive on entering CONNECTED."""
        self._last_activity = asyncio.get_running_loop().time()
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    def _teardown(self) -> None:
        """Stop background tasks, close the socket, and fail any pending command."""
        # Never cancel the task we're running in (e.g. the reader reporting its own loss)
        current = asyncio.current_task()
        for task in (self._keepalive_task, self._reader_task):
            if task and task is not current:
                task.cancel()
        self._keepalive_task = None
        self._reader_task = None

        self._close_transport()

        if self._pending and not self._pending.future.done():
            self._pending.future.set_exception(NoReply("connection lost before the hub replied"))

    def _close_transport(self) -> None:
        """Close the socket without awaiting; safe to call from sync code."""
        if self._writer:
            try:
                self._writer.close()
            except Exception as e:
                _LOGGER.debug("Error closing writer (ignored): %s", e)
        self._writer = None
        self._reader = None

    # ------------------------------------------------------------------
    # Connecting
    # ------------------------------------------------------------------

    async def _dispatch_push(self, line: str, source: str) -> None:
        """Dispatch a push event line to all registered callbacks."""
        for callback in list(self._push_callbacks):
            try:
                callback(line, source)
            except Exception as e:
                _LOGGER.error("Push callback error: %s", e)

    async def _expect(self, token: bytes, timeout: float = 5.0) -> None:
        """Read from the hub until `token` appears, raising on timeout or bad credentials."""
        buf = b""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while token not in buf:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"Timed out waiting for {token!r}")
            chunk = await asyncio.wait_for(self._reader.read(READ_CHUNK_SIZE), timeout=remaining)
            if not chunk:
                raise ConnectionError(f"Connection closed while waiting for {token!r}")
            buf += chunk
        _LOGGER.debug("Received expected token %r", token)

    async def connect(self) -> bool:
        """Start the connection manager and wait for its first login attempt.

        If that attempt fails the manager keeps retrying with backoff; call
        disconnect() to stop it.

        Returns:
            True if connected, False otherwise
        """
        if self._state is ConnState.DISCONNECTED:
            self._first_attempt = asyncio.get_running_loop().create_future()
            self._transition(ConnState.CONNECTING, "connect requested")

        if self._state is ConnState.CONNECTING and self._first_attempt and not self._first_attempt.done():
            await asyncio.shield(self._first_attempt)

        return self._state is ConnState.CONNECTED

    def _resolve_first_attempt(self, connected: bool) -> None:
        """Hand connect() the result of the first login attempt."""
        if self._first_attempt and not self._first_attempt.done():
            self._first_attempt.set_result(connected)

    async def _connection_loop(self, delay: float) -> None:
        """Log in, retrying with exponential backoff until it succeeds."""
        try:
            while True:
                if delay:
                    _LOGGER.info("Connecting to Lutron hub at %s in %ss", self.host, delay)
                    await asyncio.sleep(delay)
                if await self._open_and_login():
                    self._resolve_first_attempt(True)
                    self._transition(ConnState.CONNECTED, "logged in")
                    return
                self._resolve_first_attempt(False)
                delay = min(max(delay * 2, RECONNECT_MIN_DELAY), RECONNECT_MAX_DELAY)
        finally:
            self._resolve_first_attempt(False)

    async def _open_and_login(self) -> bool:
        """Open the socket and complete the login handshake once."""
        try:
            _LOGGER.debug("Connecting to Lutron hub at %s:%s", self.host, self.port)

            # Open TCP connection (like: telnet $LUTRON_HOST $LUTRON_PORT)
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )

            # Wait for login prompt, then send username
            await self._expect(b"login:", timeout=LOGIN_TIMEOUT)
            self._writer.write(f"{self.username}\r\n".encode())
            await self._writer.drain()

            # Wait for password prompt, then send password
            await self._expect(b"password:", timeout=LOGIN_TIMEOUT)
            self._writer.write(f"{self.password}\r\n".encode())
            await self._writer.drain()

            # Wait for GNET> prompt — confirms credentials accepted
            await self._expect(b"GNET>", timeout=LOGIN_TIMEOUT)

            _LOGGER.info("Successfully connected to Lutron hub at %s", self.host)
            return True

        except Exception as e:
            _LOGGER.error("Failed to connect to Lutron hub: %s", str(e) or type(e).__name__)
            self._close_transport()
            return False

    async def disconnect(self) -> None:
        """Close the Telnet connection on purpose (no automatic reconnect)."""
        if self._state is ConnState.DISCONNECTED:
            return

        writer = self._writer
        self._transition(ConnState.DISCONNECTED, "disconnect requested")

        if writer:
            try:
                await writer.wait_closed()
            except (asyncio.CancelledError, Exception) as e:
                # Ignore errors during cleanup
                _LOGGER.debug("Error during disconnect (ignored): %s", e)
        _LOGGER.info("Disconnected from Lutron hub")

    async def _reader_loop(self) -> None:
        """Continuously read lines from the hub socket.

        Sole consumer of self._reader. Every line counts as proof the link is
        alive. The reply to the pending command (an ~ERROR, or an ~OUTPUT for
        the zone it targeted) resolves _pending; everything else is dispatched
        as a push event. If the socket dies, reports it via _on_connection_lost.
        Runs only while CONNECTED; teardown cancels it.
        """
        reader = self._reader
        loop = asyncio.get_running_loop()
        lost_reason = None
        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        reader.readuntil(b'\n'),
                        timeout=READ_LINE_TIMEOUT
                    )
                    self._last_activity = loop.time()
                    line = data.decode(errors="replace").strip()
                    if not line or line == "GNET>":
                        continue

                    _LOGGER.debug("HUB >> %s", line)

                    # Strip GNET> prompt that sometimes prefixes the response
                    if "GNET>" in line:
                        line = line.split("GNET>")[-1].strip()

                    if not line:
                        continue

                    pending = self._pending
                    if pending and pending.matches(line):
                        pending.future.set_result(line)
                        await self._dispatch_push(line, SOURCE_INTERNAL)
                    else:
                        _LOGGER.debug("HUB PUSH >> %s", line)
                        await self._dispatch_push(line, SOURCE_EXTERNAL)

                except asyncio.TimeoutError:
                    continue
                except asyncio.IncompleteReadError:
                    lost_reason = "hub closed the connection"
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Reader loop error: %s", e)
            lost_reason = f"reader error: {e}"
        finally:
            _LOGGER.debug("Reader loop exited")
            if lost_reason:
                self._on_connection_lost(lost_reason)

    async def _keepalive_loop(self) -> None:
        """Ping the hub after PING_INTERVAL of silence.

        Any line from the hub (replies, Pico pushes) resets the silence, so a
        busy link is never pinged. The ping goes through _send_once like any
        command; a missing reply is reported there. Runs only while CONNECTED;
        teardown cancels it.
        """
        loop = asyncio.get_running_loop()
        try:
            while True:
                idle = loop.time() - self._last_activity
                if idle < PING_INTERVAL:
                    await asyncio.sleep(PING_INTERVAL - idle)
                    continue

                # ping_zone is read each time: auto-configure can change it live
                command = f"?OUTPUT,{self.ping_zone},{OUTPUT_ACTION_ZONE_LEVEL}"
                _LOGGER.debug("Sending keep-alive ping: %s", command)
                try:
                    await self._send_once(command, self.ping_zone)
                except HubError as e:
                    _LOGGER.debug("Keep-alive answered with an error; link is alive: %s", e)
                except LutronError:
                    return  # _send_once already reported the loss
                self._last_activity = loop.time()
        except asyncio.CancelledError:
            pass

    async def send_command(self, command: str, expected_zone: Optional[int] = None) -> str:
        """Send a command to the Lutron hub and return its reply.

        Never opens a connection itself. If a send gets no reply, the connection
        manager reconnects and the command is resent once the link is back.

        Args:
            command: The Lutron Integration Protocol command to send
                    (e.g., "#OUTPUT,25,1,50,1800")
            expected_zone: Only an ~OUTPUT for this zone (or an ~ERROR) counts
                    as the reply; other zones' pushes stay push events.
                    None accepts any ~OUTPUT.

        Returns:
            The hub's reply line (e.g. "~OUTPUT,25,1,50.00")

        Raises:
            NotConnected: not connected, or the link didn't come back in time
            NoReply: no reply on the final attempt
            HubError: the hub answered ~ERROR (never retried)
        """
        for attempt in range(1, COMMAND_ATTEMPTS + 1):
            if attempt > 1:
                await self._wait_connected(RECONNECT_WAIT)
            try:
                return await self._send_once(command, expected_zone)
            except NoReply as e:
                if attempt == COMMAND_ATTEMPTS:
                    raise
                _LOGGER.warning("%s; resending after reconnect", e)
        raise AssertionError("unreachable")

    async def _wait_connected(self, timeout: float) -> None:
        """Wait for the connection manager to reach CONNECTED, or raise NotConnected."""
        if self._state is ConnState.DISCONNECTED:
            raise NotConnected(f"Not connected to Lutron hub at {self.host}")
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise NotConnected(
                f"Lutron hub at {self.host} did not reconnect within {timeout}s"
            ) from None

    async def _send_once(self, command: str, expected_zone: Optional[int]) -> str:
        """Write one command and wait for its reply. The one send path.

        Any failure that means the link is dead is reported to the manager
        here, so callers only have to decide whether to retry.
        """
        # One command in flight at a time; the rest queue here in arrival order
        async with self._command_lock:
            if self._state is not ConnState.CONNECTED:
                raise NotConnected(f"Not connected to Lutron hub at {self.host}")

            # Fill the reply slot before writing so a fast reply can't slip
            # past as a push event
            pending = _PendingReply(expected_zone, asyncio.get_running_loop().create_future())
            self._pending = pending
            failure: Optional[str] = None
            cause: Optional[BaseException] = None
            try:
                _LOGGER.debug("Sending command: %s", command)

                # Send the command (like: echo "#OUTPUT,25,1,0,30:00")
                self._writer.write(f"{command}\r\n".encode())
                await self._writer.drain()

                # Wait for _reader_loop to deliver the reply
                response = await asyncio.wait_for(pending.future, timeout=REPLY_TIMEOUT)
                _LOGGER.debug("Received response: %s", response)

            except NoReply as e:
                # Teardown failed the slot: the link was already reported down
                raise NoReply(f"{e} to '{command}'") from e
            except asyncio.TimeoutError:
                # The hub always answers (~OUTPUT or ~ERROR); silence means the link is dead
                failure = f"no reply to '{command}'"
            except Exception as e:
                failure, cause = f"error sending '{command}': {e}", e
            finally:
                self._pending = None

            if failure:
                # Report only once the slot is empty, so teardown has no orphaned
                # reply to fail; the manager tears down and reconnects
                self._on_connection_lost(failure)
                raise NoReply(f"Lutron hub: {failure}") from cause

        if response.startswith("~ERROR"):
            raise HubError(command, response)

        return response

    @staticmethod
    def _seconds_to_lip_time(seconds: int) -> str:
        """Convert seconds to Lutron HH:MM:SS fade time format."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    async def set_light_level(
        self, zone_id: int, brightness: int, fade_time: int = 0
    ) -> None:
        """Set a light to a specific brightness with fade time.

        This is the key method that implements your bash script logic!

        Args:
            zone_id: The Lutron zone ID (e.g., 25, 34)
            brightness: Target brightness 0-100
            fade_time: Fade duration in seconds (e.g., 1800 for 30 minutes)

        Raises:
            LutronError: see send_command
        """
        fade_str = self._seconds_to_lip_time(fade_time)
        command = f"#OUTPUT,{zone_id},{OUTPUT_ACTION_ZONE_LEVEL},{brightness},{fade_str}"

        _LOGGER.info(
            "Setting zone %s to %s%% with %s second fade",
            zone_id,
            brightness,
            fade_time
        )

        # The hub should respond with something like: ~OUTPUT,25,1,50.00
        response = await self.send_command(command, expected_zone=zone_id)
        _LOGGER.debug("Command acknowledged by hub: %s", response)

    async def query_light_level(self, zone_id: int) -> float:
        """Query the current brightness of a light.

        This implements your query script logic.

        Args:
            zone_id: The Lutron zone ID

        Returns:
            Current brightness (0-100)

        Raises:
            LutronError: see send_command, or the reply couldn't be parsed
        """
        # Format: ?OUTPUT,<zone_id>,1
        command = f"?OUTPUT,{zone_id},{OUTPUT_ACTION_ZONE_LEVEL}"

        _LOGGER.debug("Querying zone %s level", zone_id)

        # Expected response: ~OUTPUT,25,1,75.00
        response = await self.send_command(command, expected_zone=zone_id)
        try:
            brightness = float(response.split(',')[3])
        except (ValueError, IndexError) as e:
            raise LutronError(f"Malformed reply to '{command}': {response}") from e

        _LOGGER.debug("Zone %s is at %s%%", zone_id, brightness)
        return brightness

    async def discover_zones(self, max_zones: int = DEFAULT_MAX_ZONES) -> dict[int, str]:
        """Discover all available zones on the Lutron hub.

        Queries zones sequentially to find which ones exist.

        Args:
            max_zones: Maximum zone ID to check (default: 100)

        Returns:
            Dictionary mapping zone_id to zone name (e.g., {28: "Zone 28", 15: "Zone 15"})
        """
        _LOGGER.info("Starting zone discovery (checking zones 1-%s)", max_zones)
        discovered_zones = {}

        for zone_id in range(1, max_zones + 1):
            # Query this zone; the hub answers ~ERROR,2 for IDs with no zone
            try:
                brightness = await self.query_light_level(zone_id)
            except HubError as e:
                if e.code != ERROR_OBJECT_DOES_NOT_EXIST:
                    _LOGGER.warning("Zone %s query rejected: %s", zone_id, e)
            else:
                # Zone exists!
                zone_name = f"Zone {zone_id}"
                discovered_zones[zone_id] = zone_name
                _LOGGER.info("Discovered zone %s: %s (current brightness: %s%%)",
                           zone_id, zone_name, brightness)

            await asyncio.sleep(DISCOVERY_ZONE_DELAY)

        _LOGGER.info("Discovery complete - found %s zones", len(discovered_zones))
        return discovered_zones