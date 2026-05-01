"""Tests for LutronTelnetConnection."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from custom_components.lutron_fader.lutron_telnet import LutronTelnetConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_reader(*chunks: bytes) -> AsyncMock:
    """Return a mock StreamReader that yields chunks sequentially."""
    reader = AsyncMock()
    reader.read = AsyncMock(side_effect=list(chunks))
    reader.readuntil = AsyncMock(side_effect=list(chunks))
    return reader


def make_writer() -> MagicMock:
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


def make_connection(**kwargs) -> LutronTelnetConnection:
    return LutronTelnetConnection(host="10.0.0.1", **kwargs)


# ---------------------------------------------------------------------------
# _expect
# ---------------------------------------------------------------------------

class TestExpect:
    @pytest.mark.asyncio
    async def test_token_found_in_single_chunk(self):
        conn = make_connection()
        conn._reader = make_reader(b"login: ")
        await conn._expect(b"login:")

    @pytest.mark.asyncio
    async def test_token_split_across_chunks(self):
        conn = make_connection()
        conn._reader = AsyncMock()
        conn._reader.read = AsyncMock(side_effect=[b"log", b"in: "])
        await conn._expect(b"login:")

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        conn = make_connection()
        conn._reader = AsyncMock()
        # Always return data that doesn't contain the token
        conn._reader.read = AsyncMock(side_effect=asyncio.TimeoutError)
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await conn._expect(b"login:", timeout=0.1)

    @pytest.mark.asyncio
    async def test_connection_close_raises(self):
        conn = make_connection()
        conn._reader = AsyncMock()
        conn._reader.read = AsyncMock(return_value=b"")  # EOF
        with pytest.raises(ConnectionError):
            await conn._expect(b"login:")


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

class TestConnect:
    @pytest.mark.asyncio
    async def test_successful_connect(self):
        conn = make_connection()
        reader = AsyncMock()
        writer = make_writer()

        # Feed login:, password:, GNET> prompts
        reader.read = AsyncMock(side_effect=[b"login: ", b"password: ", b"GNET> "])

        with patch("asyncio.open_connection", return_value=(reader, writer)):
            result = await conn.connect()

        assert result is True
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_wrong_credentials_returns_false(self):
        conn = make_connection()
        reader = AsyncMock()
        writer = make_writer()

        # Hub closes connection after password (empty = EOF)
        reader.read = AsyncMock(side_effect=[b"login: ", b"password: ", b""])

        with patch("asyncio.open_connection", return_value=(reader, writer)):
            result = await conn.connect()

        assert result is False
        assert conn.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_failure_returns_false(self):
        conn = make_connection()
        with patch("asyncio.open_connection", side_effect=OSError("refused")):
            result = await conn.connect()

        assert result is False
        assert conn.is_connected is False

    @pytest.mark.asyncio
    async def test_already_connected_returns_true(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()
        conn._disconnect_timer = MagicMock()
        conn._disconnect_timer.cancel = MagicMock()

        with patch.object(conn, '_reset_disconnect_timer') as mock_reset:
            result = await conn.connect()

        assert result is True
        mock_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_username_and_password(self):
        conn = make_connection(username="lutron", password="integration")
        reader = AsyncMock()
        writer = make_writer()
        reader.read = AsyncMock(side_effect=[b"login: ", b"password: ", b"GNET> "])

        with patch("asyncio.open_connection", return_value=(reader, writer)):
            await conn.connect()

        written = b"".join(c.args[0] for c in writer.write.call_args_list)
        assert b"lutron\r\n" in written
        assert b"integration\r\n" in written


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()
        conn._reader = AsyncMock()

        await conn.disconnect()

        assert conn.is_connected is False
        assert conn._writer is None
        assert conn._reader is None

    @pytest.mark.asyncio
    async def test_disconnect_cancels_timers(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()

        disconnect_timer = MagicMock()
        ping_timer = MagicMock()
        conn._disconnect_timer = disconnect_timer
        conn._ping_timer = ping_timer

        await conn.disconnect()

        disconnect_timer.cancel.assert_called_once()
        ping_timer.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected_is_safe(self):
        conn = make_connection()
        await conn.disconnect()  # Should not raise


# ---------------------------------------------------------------------------
# send_command
# ---------------------------------------------------------------------------

class TestSendCommand:
    @pytest.mark.asyncio
    async def test_sends_command_with_crlf(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()

        with patch.object(conn, '_reset_disconnect_timer'), \
             patch.object(conn, '_reset_ping_timer'), \
             patch.object(conn, '_read_response', return_value="~OUTPUT,25,1,50.00"):
            await conn.send_command("#OUTPUT,25,1,50,0")

        written = b"".join(c.args[0] for c in conn._writer.write.call_args_list)
        assert written == b"#OUTPUT,25,1,50,0\r\n"

    @pytest.mark.asyncio
    async def test_reconnects_when_disconnected(self):
        conn = make_connection()
        conn._connected = False

        with patch.object(conn, 'connect', return_value=False) as mock_connect:
            result = await conn.send_command("#OUTPUT,25,1,50,0")

        mock_connect.assert_called_once()
        assert result is None

    @pytest.mark.asyncio
    async def test_null_writer_returns_none(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = None  # Simulate concurrent disconnect

        with patch.object(conn, '_reset_disconnect_timer'), \
             patch.object(conn, '_reset_ping_timer'):
            result = await conn.send_command("#OUTPUT,25,1,50,0")

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_triggers_disconnect(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()
        conn._writer.drain = AsyncMock(side_effect=OSError("broken pipe"))

        with patch.object(conn, '_reset_disconnect_timer'), \
             patch.object(conn, '_reset_ping_timer'), \
             patch.object(conn, 'disconnect') as mock_disconnect:
            result = await conn.send_command("#OUTPUT,25,1,50,0")

        mock_disconnect.assert_called_once()
        assert result is None


# ---------------------------------------------------------------------------
# _read_response
# ---------------------------------------------------------------------------

class TestReadResponse:
    def _make_conn_with_lines(self, *lines: bytes) -> LutronTelnetConnection:
        conn = make_connection()
        conn._reader = AsyncMock()
        # Each line is returned by readuntil, then TimeoutError to end the loop
        conn._reader.readuntil = AsyncMock(
            side_effect=list(lines) + [asyncio.TimeoutError]
        )
        return conn

    @pytest.mark.asyncio
    async def test_normal_output_response(self):
        conn = self._make_conn_with_lines(b"~OUTPUT,25,1,50.00\n")
        result = await conn._read_response()
        assert result == "~OUTPUT,25,1,50.00"

    @pytest.mark.asyncio
    async def test_output_after_gnet_prompt(self):
        conn = self._make_conn_with_lines(b"GNET> ~OUTPUT,25,1,75.00\n")
        result = await conn._read_response()
        assert result == "~OUTPUT,25,1,75.00"

    @pytest.mark.asyncio
    async def test_device_response(self):
        conn = self._make_conn_with_lines(b"~DEVICE,1,2,3\n")
        result = await conn._read_response()
        assert result == "~DEVICE,1,2,3"

    @pytest.mark.asyncio
    async def test_malformed_output_missing_tilde(self):
        conn = self._make_conn_with_lines(b"OUTPUT,25,1,50.00\n")
        result = await conn._read_response()
        assert result == "~OUTPUT,25,1,50.00"

    @pytest.mark.asyncio
    async def test_garbage_returns_empty_string(self):
        conn = self._make_conn_with_lines(b"GNET> \n", b"some garbage\n")
        result = await conn._read_response()
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_string(self):
        conn = make_connection()
        conn._reader = AsyncMock()
        conn._reader.readuntil = AsyncMock(side_effect=asyncio.TimeoutError)
        result = await conn._read_response()
        assert result == ""

    @pytest.mark.asyncio
    async def test_non_output_csv_not_matched(self):
        # A line like "25,50,garbage" that looks numeric but isn't OUTPUT
        conn = self._make_conn_with_lines(b"hello,world,123\n")
        result = await conn._read_response()
        assert result == ""


# ---------------------------------------------------------------------------
# set_light_level
# ---------------------------------------------------------------------------

class TestSetLightLevel:
    @pytest.mark.asyncio
    async def test_correct_command_format(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00") as mock_send:
            await conn.set_light_level(zone_id=25, brightness=50, fade_time=1800)

        mock_send.assert_called_once_with("#OUTPUT,25,1,50,1800")

    @pytest.mark.asyncio
    async def test_returns_true_on_valid_response(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00"):
            result = await conn.set_light_level(25, 50, 0)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_no_response(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value=None):
            result = await conn.set_light_level(25, 50, 0)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_unexpected_response(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~ERROR"):
            result = await conn.set_light_level(25, 50, 0)
        assert result is False

    @pytest.mark.asyncio
    async def test_default_fade_time_is_zero(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00") as mock_send:
            await conn.set_light_level(25, 50)
        mock_send.assert_called_once_with("#OUTPUT,25,1,50,0")


# ---------------------------------------------------------------------------
# query_light_level
# ---------------------------------------------------------------------------

class TestQueryLightLevel:
    @pytest.mark.asyncio
    async def test_correct_command_format(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,75.00") as mock_send:
            await conn.query_light_level(25)
        mock_send.assert_called_once_with("?OUTPUT,25,1")

    @pytest.mark.asyncio
    async def test_parses_brightness(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,75.00"):
            result = await conn.query_light_level(25)
        assert result == 75.0

    @pytest.mark.asyncio
    async def test_parses_zero_brightness(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,0.00"):
            result = await conn.query_light_level(25)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_returns_none_on_no_response(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value=None):
            result = await conn.query_light_level(25)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_response(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1"):
            result = await conn.query_light_level(25)
        assert result is None
