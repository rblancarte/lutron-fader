"""Lutron Telnet communication handler."""
import asyncio
import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Auto-disconnect after 5 minutes of inactivity
DISCONNECT_TIMEOUT = 300  # seconds

# Ping interval - query zone 1 every minute when connected
PING_INTERVAL = 60  # seconds


class LutronTelnetConnection:
    """Manages Telnet connection to Lutron Caseta Pro hub with auto-disconnect."""

    def __init__(self, host: str, port: int = 23, username: str = "lutron", password: str = "integration"):
        """Initialize the Telnet connection.
        
        Args:
            host: IP address of the Lutron hub (e.g., "10.0.1.111")
            port: Telnet port (default: 23)
            username: Telnet username (default: "lutron")
            password: Telnet password (default: "integration")
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._disconnect_timer: Optional[asyncio.Task] = None
        self._ping_timer: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Establish connection to the Lutron hub.
        
        Returns:
            True if connection successful, False otherwise
        """
        # If already connected, just reset the timer
        if self._connected:
            _LOGGER.debug("Already connected, resetting disconnect timer")
            self._reset_disconnect_timer()
            return True
        
        try:
            _LOGGER.debug("Connecting to Lutron hub at %s:%s", self.host, self.port)
            
            # Open TCP connection (like: telnet $LUTRON_HOST $LUTRON_PORT)
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            
            # Wait for login prompt and send username
            await asyncio.sleep(1)
            self._writer.write(f"{self.username}\r\n".encode())
            await self._writer.drain()
            
            # Wait and send password
            await asyncio.sleep(1)
            self._writer.write(f"{self.password}\r\n".encode())
            await self._writer.drain()
            
            # Give it a moment to authenticate
            await asyncio.sleep(1)
            
            self._connected = True
            _LOGGER.info("Successfully connected to Lutron hub at %s", self.host)

            # Start the auto-disconnect timer
            self._reset_disconnect_timer()

            # Start the ping timer
            self._start_ping_timer()

            return True
            
        except Exception as e:
            _LOGGER.error("Failed to connect to Lutron hub: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the Telnet connection."""
        # Cancel the auto-disconnect timer
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None

        # Cancel the ping timer
        if self._ping_timer:
            self._ping_timer.cancel()
            self._ping_timer = None

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

    def _reset_disconnect_timer(self) -> None:
        """Reset the auto-disconnect timer.

        Called whenever a command is sent to keep the connection alive.
        """
        # Cancel existing timer if any
        if self._disconnect_timer:
            self._disconnect_timer.cancel()

        # Create new timer
        self._disconnect_timer = asyncio.create_task(self._auto_disconnect())
        _LOGGER.debug("Disconnect timer reset to %s seconds", DISCONNECT_TIMEOUT)

    async def _auto_disconnect(self) -> None:
        """Auto-disconnect after timeout period.

        This runs in the background and disconnects if no commands are sent.
        """
        try:
            await asyncio.sleep(DISCONNECT_TIMEOUT)
            _LOGGER.info("Auto-disconnecting after %s seconds of inactivity", DISCONNECT_TIMEOUT)
            await self.disconnect()
        except asyncio.CancelledError:
            # Timer was cancelled (new command came in), this is normal
            pass

    def _start_ping_timer(self) -> None:
        """Start the ping timer to query zone 1 every minute.

        The ping does NOT reset the disconnect timer, so the connection
        will still auto-disconnect after 5 minutes of user inactivity.
        """
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

    async def _ping_loop(self) -> None:
        """Continuously ping zone 1 to monitor connection status.

        This does NOT reset the disconnect timer.
        """
        try:
            while self._connected:
                await asyncio.sleep(PING_INTERVAL)
                if self._connected:  # Check again after sleep
                    await self._send_ping()
        except asyncio.CancelledError:
            # Timer was cancelled (disconnect called), this is normal
            pass

    async def _send_ping(self) -> None:
        """Send a ping query to zone 1 without resetting the disconnect timer.

        This is an internal method that bypasses the normal command flow.
        """
        if not self._connected or not self._writer:
            return

        try:
            command = "?OUTPUT,1,1"
            _LOGGER.debug("Sending ping: %s", command)

            # Send the command directly without calling send_command()
            # This way we don't reset the disconnect timer
            self._writer.write(f"{command}\r\n".encode())
            await self._writer.drain()

            # Wait a moment for the response
            await asyncio.sleep(0.5)

            # Read the response
            response = await self._read_response()
            if response and response.startswith("~OUTPUT"):
                try:
                    # Parse the brightness from response
                    parts = response.split(',')
                    if len(parts) >= 4:
                        brightness = float(parts[3])
                        _LOGGER.debug("Ping response - Zone 1 is at %s%%", brightness)
                except (ValueError, IndexError) as e:
                    _LOGGER.debug("Error parsing ping response '%s': %s", response, e)
            else:
                _LOGGER.debug("Ping received no valid response: '%s'", response)

        except Exception as e:
            _LOGGER.debug("Error sending ping: %s", e)
            # Don't disconnect on ping errors - let the disconnect timer handle it

    async def send_command(self, command: str) -> Optional[str]:
        """Send a command to the Lutron hub.

        This is like echoing a command in your bash script.

        Args:
            command: The Lutron Integration Protocol command to send
                    (e.g., "#OUTPUT,25,1,50,1800")

        Returns:
            Response from the hub, or None if error
        """
        # Connect if not already connected
        if not self._connected:
            success = await self.connect()
            if not success:
                _LOGGER.error("Failed to connect before sending command")
                return None

        # Reset the disconnect timer since we're sending a command
        self._reset_disconnect_timer()

        # Reset the ping timer to avoid redundant ping right after a command
        self._reset_ping_timer()

        try:
            _LOGGER.debug("Sending command: %s", command)

            # Send the command (like: echo "#OUTPUT,25,1,0,30:00")
            self._writer.write(f"{command}\r\n".encode())
            await self._writer.drain()

            # Wait a moment for the response
            await asyncio.sleep(0.5)

            # Read the response
            response = await self._read_response()
            _LOGGER.debug("Received response: %s", response)

            return response

        except Exception as e:
            _LOGGER.error("Error sending command '%s': %s", command, e)
            # Connection might be broken, disconnect and retry next time
            await self.disconnect()
            return None

    async def _read_response(self) -> str:
        """Read response from the hub.

        Returns:
            The response string from the hub (cleaned of prompts)
        """
        try:
            # Read all available data (there may be multiple lines with prompts)
            await asyncio.sleep(0.1)  # Give the hub time to send all data

            # Read everything available
            full_response = ""
            while True:
                try:
                    data = await asyncio.wait_for(
                        self._reader.readuntil(b'\n'),
                        timeout=0.5
                    )
                    full_response += data.decode()
                except asyncio.TimeoutError:
                    # No more data available
                    break

            # Look for the actual response (starts with ~ or #)
            # The response may be mixed with prompts like "login: password: GNET> ~OUTPUT,..."
            for line in full_response.split('\n'):
                # Find lines that contain actual responses (not prompts)
                if '~OUTPUT' in line or '~DEVICE' in line:
                    # Extract just the response part (after the last prompt)
                    if 'GNET>' in line:
                        # Response is after the GNET> prompt
                        response = line.split('GNET>')[-1].strip()
                        return response
                    else:
                        # Just return the cleaned line
                        return line.strip()

            # No response found - return empty string for cleaner error handling
            _LOGGER.debug("No valid response found in: %s", full_response)
            return ""

        except Exception as e:
            _LOGGER.error("Error reading response: %s", e)
            return ""

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
        # Format: #OUTPUT,<zone_id>,1,<brightness>,<fade_time>
        command = f"#OUTPUT,{zone_id},1,{brightness},{fade_time}"

        _LOGGER.info(
            "Setting zone %s to %s%% with %s second fade",
            zone_id,
            brightness,
            fade_time
        )

        response = await self.send_command(command)

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
        command = f"?OUTPUT,{zone_id},1"

        _LOGGER.debug("Querying zone %s level", zone_id)

        response = await self.send_command(command)

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