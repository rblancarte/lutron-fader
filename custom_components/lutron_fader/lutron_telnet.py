"""Lutron Telnet communication handler."""
import asyncio
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Telnet defaults
DEFAULT_TELNET_PORT = 23

# Keep-alive
PING_INTERVAL = 60         # seconds between keep-alive pings

# Reconnect backoff after an unexpected connection loss
RECONNECT_MIN_DELAY = 5    # seconds before the first reconnect attempt
RECONNECT_MAX_DELAY = 300  # cap for exponential backoff

# Auth handshake timing
LOGIN_TIMEOUT = 5.0        # seconds to wait for each login prompt
READ_CHUNK_SIZE = 256      # bytes per read chunk in _expect

# Command I/O timing
READ_LINE_TIMEOUT = 0.5    # per-line read timeout in _reader_loop

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

# Push event source tags
SOURCE_INTERNAL = "internal"  # ~OUTPUT echoed back from a command we sent
SOURCE_EXTERNAL = "external"  # unsolicited push from Pico, app, or another system


class LutronTelnetConnection:
    """Manages Telnet connection to Lutron Caseta Pro hub with auto-disconnect."""

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
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._ping_timer: Optional[asyncio.Task] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending_response: Optional[asyncio.Future] = None
        self._pending_zone: Optional[int] = None  # zone whose ~OUTPUT answers the pending command
        self._push_callbacks: list = []
        self._availability_callbacks: list = []
        self._connect_lock = asyncio.Lock()  # Prevent concurrent connection attempts
        self._command_lock = asyncio.Lock()  # Serialize command/response cycles

        # Connection-loss handling
        self._auto_reconnect = False  # True once connected; False after an explicit disconnect()
        self._lost = False            # True from an unexpected loss until the next successful connect
        self._reconnect_task: Optional[asyncio.Task] = None

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

    def _set_lost(self, lost: bool) -> None:
        """Update the lost flag and notify availability callbacks on change."""
        if self._lost == lost:
            return
        self._lost = lost
        for callback in list(self._availability_callbacks):
            try:
                callback(not lost)
            except Exception as e:
                _LOGGER.error("Availability callback error: %s", e)

    @property
    def available(self) -> bool:
        """Return False only while recovering from an unexpected connection loss.

        A connection that was never opened or was closed on purpose is still
        "available" — send_command connects lazily.
        """
        return not self._lost

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
        """Establish connection to the Lutron hub.

        Returns:
            True if connection successful, False otherwise
        """
        # Use a lock to prevent concurrent connection attempts
        async with self._connect_lock:
            # If already connected, just reset the timer
            if self._connected:
                _LOGGER.debug("Already connected")
                return True

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

                self._connected = True
                self._auto_reconnect = True
                _LOGGER.info("Successfully connected to Lutron hub at %s", self.host)

                # Start background tasks
                self._start_ping_timer()
                self._start_reader_task()

                self._set_lost(False)
                return True

            except Exception as e:
                _LOGGER.error("Failed to connect to Lutron hub: %s", e)
                self._connected = False
                self._close_transport()
                return False

    def _close_transport(self) -> None:
        """Close the socket without awaiting; safe to call from sync code."""
        if self._writer:
            try:
                self._writer.close()
            except Exception as e:
                _LOGGER.debug("Error closing writer (ignored): %s", e)
        self._writer = None
        self._reader = None

    def _handle_connection_lost(self, reason: str) -> None:
        """Tear down a connection that died unexpectedly and schedule a reconnect."""
        if not self._connected and self._writer is None:
            return  # already torn down (or never connected)

        _LOGGER.warning("Lost connection to Lutron hub at %s: %s", self.host, reason)
        self._connected = False

        # Cancel background tasks, but never the task we're running in
        current = asyncio.current_task()
        for task in (self._ping_timer, self._reader_task):
            if task and task is not current:
                task.cancel()
        self._ping_timer = None
        self._reader_task = None

        self._close_transport()

        if self._pending_response and not self._pending_response.done():
            self._pending_response.set_result("")

        self._set_lost(True)
        if self._auto_reconnect:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Start the reconnect loop unless one is already running."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Retry connect() with exponential backoff until it succeeds."""
        delay = RECONNECT_MIN_DELAY
        try:
            while self._auto_reconnect and not self._connected:
                _LOGGER.info("Reconnecting to Lutron hub at %s in %ss", self.host, delay)
                await asyncio.sleep(delay)
                if not self._auto_reconnect or self._connected:
                    return
                if await self.connect():
                    return
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
        except asyncio.CancelledError:
            pass

    async def disconnect(self) -> None:
        """Close the Telnet connection on purpose (no automatic reconnect)."""
        self._auto_reconnect = False
        if self._reconnect_task and self._reconnect_task is not asyncio.current_task():
            self._reconnect_task.cancel()
        self._reconnect_task = None

        # Cancel background tasks
        if self._ping_timer:
            self._ping_timer.cancel()
            self._ping_timer = None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

        if self._writer:
            _LOGGER.debug("Disconnecting from Lutron hub")
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (asyncio.CancelledError, Exception) as e:
                # Ignore errors during cleanup
                _LOGGER.debug("Error during disconnect (ignored): %s", e)
            finally:
                self._connected = False
                self._writer = None
                self._reader = None
                _LOGGER.info("Disconnected from Lutron hub")

    def _start_ping_timer(self) -> None:
        """Start the ping timer to query zone 1 every minute."""
        # Cancel existing timer if any
        if self._ping_timer:
            self._ping_timer.cancel()

        # Create new timer
        self._ping_timer = asyncio.create_task(self._ping_loop())
        _LOGGER.debug("Ping timer started with %s second interval", PING_INTERVAL)

    def _reset_ping_timer(self) -> None:
        """Reset the ping timer.

        Called when a user command is sent to avoid redundant pings.
        """
        # Cancel existing timer if any
        if self._ping_timer:
            self._ping_timer.cancel()

        # Create new timer
        self._ping_timer = asyncio.create_task(self._ping_loop())
        _LOGGER.debug("Ping timer reset to %s seconds", PING_INTERVAL)

    def _start_reader_task(self) -> None:
        """Start the background reader task."""
        if self._reader_task:
            self._reader_task.cancel()
        self._reader_task = asyncio.create_task(self._reader_loop())
        _LOGGER.debug("Reader task started")

    async def _reader_loop(self) -> None:
        """Continuously read lines from the hub socket.

        Sole consumer of self._reader. Routes the reply to the pending command
        (an ~ERROR, or an ~OUTPUT for the zone the command targeted) to
        _pending_response; everything else is dispatched as a push event.
        If the socket dies, hands off to _handle_connection_lost.
        """
        lost_reason = None
        try:
            while self._connected and self._reader:
                try:
                    data = await asyncio.wait_for(
                        self._reader.readuntil(b'\n'),
                        timeout=READ_LINE_TIMEOUT
                    )
                    line = data.decode(errors="replace").strip()
                    if not line or line == "GNET>":
                        continue

                    _LOGGER.debug("HUB >> %s", line)

                    # Strip GNET> prompt that sometimes prefixes the response
                    if "GNET>" in line:
                        line = line.split("GNET>")[-1].strip()

                    if not line:
                        continue

                    if self._is_pending_reply(line):
                        self._pending_response.set_result(line)
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
                self._handle_connection_lost(lost_reason)

    def _is_pending_reply(self, line: str) -> bool:
        """Return True if `line` answers the command currently awaiting a reply."""
        if not self._pending_response or self._pending_response.done():
            return False
        if line.startswith("~ERROR"):
            return True
        if not line.startswith("~OUTPUT"):
            return False
        if self._pending_zone is None:
            return True
        parts = line.split(",")
        return len(parts) > 1 and parts[1].strip() == str(self._pending_zone)

    async def _ping_loop(self) -> None:
        """Periodically ping the hub; tear the connection down if it stops answering."""
        try:
            while self._connected:
                await asyncio.sleep(PING_INTERVAL)
                if self._connected:  # Check again after sleep
                    if not await self._send_ping():
                        self._handle_connection_lost("keep-alive ping got no reply")
                        return
        except asyncio.CancelledError:
            # Timer was cancelled (disconnect called), this is normal
            pass

    async def _send_ping(self) -> bool:
        """Send a keep-alive query to the ping zone.

        This is an internal method that bypasses the normal command flow
        (it does not reset the ping timer).

        Returns:
            True if the hub answered (even with ~ERROR), False otherwise
        """
        if not self._connected or not self._writer:
            return True  # nothing to check

        try:
            command = f"?OUTPUT,{self.ping_zone},{OUTPUT_ACTION_ZONE_LEVEL}"
            _LOGGER.debug("Sending ping: %s", command)

            async with self._command_lock:
                self._arm_response(self.ping_zone)
                self._writer.write(f"{command}\r\n".encode())
                await self._writer.drain()

                response = await self._await_response()
            if response and response.startswith("~OUTPUT"):
                try:
                    # Parse the brightness from response
                    parts = response.split(',')
                    if len(parts) >= 4:
                        brightness = float(parts[3])
                        _LOGGER.debug("Ping response - Zone %s is at %s%%", self.ping_zone, brightness)
                except (ValueError, IndexError) as e:
                    _LOGGER.debug("Error parsing ping response '%s': %s", response, e)
            else:
                _LOGGER.debug("Ping received no valid response: '%s'", response)
            return bool(response)

        except Exception as e:
            _LOGGER.debug("Error sending ping: %s", e)
            return False

    async def send_command(self, command: str, expected_zone: Optional[int] = None) -> Optional[str]:
        """Send a command to the Lutron hub.

        This is like echoing a command in your bash script.

        Args:
            command: The Lutron Integration Protocol command to send
                    (e.g., "#OUTPUT,25,1,50,1800")
            expected_zone: Only an ~OUTPUT for this zone (or an ~ERROR) counts
                    as the reply; other zones' pushes stay push events.
                    None accepts any ~OUTPUT.

        Returns:
            Response from the hub, or None if error
        """
        # Connect if not already connected
        if not self._connected:
            success = await self.connect()
            if not success:
                _LOGGER.error("Failed to connect before sending command")
                return None

        # Use a lock to serialize command/response cycles
        # This prevents multiple coroutines from reading the same stream simultaneously
        async with self._command_lock:
            # Reset the ping timer to avoid redundant ping right after a command
            self._reset_ping_timer()

            try:
                _LOGGER.debug("Sending command: %s", command)

                if not self._writer:
                    _LOGGER.error("Writer is None after connect — concurrent disconnect?")
                    return None

                # Arm the reply slot before writing so a fast reply can't slip
                # past as a push event
                self._arm_response(expected_zone)

                # Send the command (like: echo "#OUTPUT,25,1,0,30:00")
                self._writer.write(f"{command}\r\n".encode())
                await self._writer.drain()

                # Wait for _reader_loop to deliver the response
                response = await self._await_response()
                _LOGGER.debug("Received response: %s", response)

                if not response and self._connected:
                    # The hub always answers (~OUTPUT or ~ERROR); silence means the link is dead
                    self._handle_connection_lost(f"no reply to '{command}'")

                return response

            except Exception as e:
                _LOGGER.error("Error sending command '%s': %s", command, e)
                self._pending_response = None
                self._pending_zone = None
                # Connection is broken; tear down and reconnect in the background
                self._handle_connection_lost(f"error sending command: {e}")
                return None

    def _arm_response(self, expected_zone: Optional[int]) -> None:
        """Create the future _reader_loop resolves with the next matching reply."""
        self._pending_zone = expected_zone
        self._pending_response = asyncio.get_running_loop().create_future()

    async def _await_response(self, timeout: float = 5.0) -> str:
        """Wait for _reader_loop to deliver the reply to the armed command.

        Arms a reply slot (accepting any zone) if the caller didn't.
        """
        if self._pending_response is None:
            self._arm_response(None)
        try:
            return await asyncio.wait_for(self._pending_response, timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.debug("Timed out waiting for hub response")
            return ""
        finally:
            self._pending_response = None
            self._pending_zone = None

    @staticmethod
    def _seconds_to_lip_time(seconds: int) -> str:
        """Convert seconds to Lutron HH:MM:SS fade time format."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    async def set_light_level(
        self, zone_id: int, brightness: int, fade_time: int = 0
    ) -> bool:
        """Set a light to a specific brightness with fade time.

        This is the key method that implements your bash script logic!

        Args:
            zone_id: The Lutron zone ID (e.g., 25, 34)
            brightness: Target brightness 0-100
            fade_time: Fade duration in seconds (e.g., 1800 for 30 minutes)

        Returns:
            True if command sent successfully, False otherwise
        """
        fade_str = self._seconds_to_lip_time(fade_time)
        command = f"#OUTPUT,{zone_id},{OUTPUT_ACTION_ZONE_LEVEL},{brightness},{fade_str}"

        _LOGGER.info(
            "Setting zone %s to %s%% with %s second fade",
            zone_id,
            brightness,
            fade_time
        )

        response = await self.send_command(command, expected_zone=zone_id)

        # The hub should respond with something like: ~OUTPUT,25,1,50.00
        if response and response.startswith("~OUTPUT"):
            _LOGGER.debug("Command acknowledged by hub")
            return True
        else:
            _LOGGER.warning("Unexpected or no response from hub: %s", response)
            return False

    async def query_light_level(self, zone_id: int) -> Optional[float]:
        """Query the current brightness of a light.

        This implements your query script logic.

        Args:
            zone_id: The Lutron zone ID

        Returns:
            Current brightness (0-100), or None if error
        """
        # Format: ?OUTPUT,<zone_id>,1
        command = f"?OUTPUT,{zone_id},{OUTPUT_ACTION_ZONE_LEVEL}"

        _LOGGER.debug("Querying zone %s level", zone_id)

        response = await self.send_command(command, expected_zone=zone_id)

        # Expected response: ~OUTPUT,25,1,75.00
        if response and response.startswith("~OUTPUT"):
            try:
                # Parse the brightness from response
                parts = response.split(',')
                if len(parts) >= 4:
                    brightness = float(parts[3])
                    _LOGGER.debug("Zone %s is at %s%%", zone_id, brightness)
                    return brightness
            except (ValueError, IndexError) as e:
                _LOGGER.error("Error parsing response '%s': %s", response, e)
        else:
            _LOGGER.warning("Query failed - invalid or no response: '%s'", response)

        return None

    @property
    def is_connected(self) -> bool:
        """Return whether we're connected to the hub."""
        return self._connected

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
            # Query this zone
            brightness = await self.query_light_level(zone_id)

            if brightness is not None:
                # Zone exists!
                zone_name = f"Zone {zone_id}"
                discovered_zones[zone_id] = zone_name
                _LOGGER.info("Discovered zone %s: %s (current brightness: %s%%)",
                           zone_id, zone_name, brightness)

            await asyncio.sleep(DISCOVERY_ZONE_DELAY)

        _LOGGER.info("Discovery complete - found %s zones", len(discovered_zones))
        return discovered_zones