"""Tests for LutronTelnetConnection."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'lutron_fader'))

from lutron_telnet import LutronTelnetConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_reader(*lines: bytes) -> AsyncMock:
    """Return a mock StreamReader that yields lines then TimeoutError."""
    reader = AsyncMock()
    reader.read = AsyncMock(side_effect=list(lines))
    reader.readuntil = AsyncMock(side_effect=list(lines) + [asyncio.TimeoutError])
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
        reader.read = AsyncMock(side_effect=[b"login: ", b"password: ", b"GNET> "])

        with patch("asyncio.open_connection", return_value=(reader, writer)), \
             patch.object(conn, '_start_ping_timer'), \
             patch.object(conn, '_start_reader_task'):
            result = await conn.connect()

        assert result is True
        assert conn.is_connected is True

    @pytest.mark.asyncio
    async def test_wrong_credentials_returns_false(self):
        conn = make_connection()
        reader = AsyncMock()
        writer = make_writer()
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

        result = await conn.connect()
        assert result is True

    @pytest.mark.asyncio
    async def test_sends_username_and_password(self):
        conn = make_connection(username="lutron", password="integration")
        reader = AsyncMock()
        writer = make_writer()
        reader.read = AsyncMock(side_effect=[b"login: ", b"password: ", b"GNET> "])

        with patch("asyncio.open_connection", return_value=(reader, writer)), \
             patch.object(conn, '_start_ping_timer'), \
             patch.object(conn, '_start_reader_task'):
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
    async def test_disconnect_cancels_tasks(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()

        ping_timer = MagicMock()
        reader_task = MagicMock()
        conn._ping_timer = ping_timer
        conn._reader_task = reader_task

        await conn.disconnect()

        ping_timer.cancel.assert_called_once()
        reader_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected_is_safe(self):
        conn = make_connection()
        await conn.disconnect()  # Should not raise


# ---------------------------------------------------------------------------
# _await_response
# ---------------------------------------------------------------------------

class TestAwaitResponse:
    @pytest.mark.asyncio
    async def test_resolves_when_future_set(self):
        conn = make_connection()

        async def set_result():
            await asyncio.sleep(0.05)
            if conn._pending_response and not conn._pending_response.done():
                conn._pending_response.set_result("~OUTPUT,5,1,50.00")

        asyncio.create_task(set_result())
        result = await conn._await_response(timeout=1.0)
        assert result == "~OUTPUT,5,1,50.00"

    @pytest.mark.asyncio
    async def test_returns_empty_on_timeout(self):
        conn = make_connection()
        result = await conn._await_response(timeout=0.05)
        assert result == ""

    @pytest.mark.asyncio
    async def test_clears_pending_response_after_timeout(self):
        conn = make_connection()
        await conn._await_response(timeout=0.05)
        assert conn._pending_response is None

    @pytest.mark.asyncio
    async def test_clears_pending_response_after_resolve(self):
        conn = make_connection()

        async def set_result():
            await asyncio.sleep(0.05)
            if conn._pending_response and not conn._pending_response.done():
                conn._pending_response.set_result("~OUTPUT,5,1,100.00")

        asyncio.create_task(set_result())
        await conn._await_response(timeout=1.0)
        assert conn._pending_response is None


# ---------------------------------------------------------------------------
# _reader_loop
# ---------------------------------------------------------------------------

class TestReaderLoop:
    async def _run_loop_with_lines(self, conn, lines: list[bytes]):
        """Feed lines into the reader loop then stop it."""
        conn._reader = AsyncMock()
        conn._connected = True

        # After all lines, raise CancelledError to stop the loop cleanly
        conn._reader.readuntil = AsyncMock(
            side_effect=lines + [asyncio.CancelledError]
        )
        try:
            await conn._reader_loop()
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_routes_output_to_pending_future(self):
        conn = make_connection()
        future = asyncio.get_event_loop().create_future()
        conn._pending_response = future

        await self._run_loop_with_lines(conn, [b"~OUTPUT,5,1,50.00\n"])

        assert future.done()
        assert future.result() == "~OUTPUT,5,1,50.00"

    @pytest.mark.asyncio
    async def test_routes_error_to_pending_future(self):
        conn = make_connection()
        future = asyncio.get_event_loop().create_future()
        conn._pending_response = future

        await self._run_loop_with_lines(conn, [b"~ERROR\n"])

        assert future.done()
        assert future.result() == "~ERROR"

    @pytest.mark.asyncio
    async def test_push_event_does_not_resolve_future(self):
        """Unsolicited ~OUTPUT with no pending future should not crash."""
        conn = make_connection()
        conn._pending_response = None

        # Should complete without error
        await self._run_loop_with_lines(conn, [b"~OUTPUT,5,1,75.00\n"])

    @pytest.mark.asyncio
    async def test_skips_bare_gnet_prompt(self):
        conn = make_connection()
        future = asyncio.get_event_loop().create_future()
        conn._pending_response = future

        # Bare GNET> line should be skipped; ~OUTPUT resolves the future
        await self._run_loop_with_lines(conn, [b"GNET>\n", b"~OUTPUT,5,1,25.00\n"])

        assert future.done()
        assert future.result() == "~OUTPUT,5,1,25.00"

    @pytest.mark.asyncio
    async def test_strips_gnet_prefix_from_response(self):
        conn = make_connection()
        future = asyncio.get_event_loop().create_future()
        conn._pending_response = future

        # GNET> prefixed on the same line as ~OUTPUT
        await self._run_loop_with_lines(conn, [b"GNET> ~OUTPUT,5,1,100.00\n"])

        assert future.done()
        assert future.result() == "~OUTPUT,5,1,100.00"

    @pytest.mark.asyncio
    async def test_incomplete_read_sets_disconnected(self):
        conn = make_connection()
        conn._connected = True
        conn._reader = AsyncMock()
        conn._reader.readuntil = AsyncMock(
            side_effect=asyncio.IncompleteReadError(b"", 1)
        )

        await conn._reader_loop()

        assert conn._connected is False


# ---------------------------------------------------------------------------
# send_command
# ---------------------------------------------------------------------------

class TestSendCommand:
    @pytest.mark.asyncio
    async def test_sends_command_with_crlf(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()

        with patch.object(conn, '_reset_ping_timer'), \
             patch.object(conn, '_await_response', return_value="~OUTPUT,25,1,50.00"):
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
        conn._writer = None

        with patch.object(conn, '_reset_ping_timer'):
            result = await conn.send_command("#OUTPUT,25,1,50,0")

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_triggers_disconnect(self):
        conn = make_connection()
        conn._connected = True
        conn._writer = make_writer()
        conn._writer.drain = AsyncMock(side_effect=OSError("broken pipe"))

        with patch.object(conn, '_reset_ping_timer'), \
             patch.object(conn, 'disconnect') as mock_disconnect:
            result = await conn.send_command("#OUTPUT,25,1,50,0")

        mock_disconnect.assert_called_once()
        assert result is None


# ---------------------------------------------------------------------------
# set_light_level
# ---------------------------------------------------------------------------

class TestSecondsToLipTime:
    def test_zero(self):
        assert LutronTelnetConnection._seconds_to_lip_time(0) == "00:00:00"

    def test_under_60(self):
        assert LutronTelnetConnection._seconds_to_lip_time(10) == "00:00:10"
        assert LutronTelnetConnection._seconds_to_lip_time(59) == "00:00:59"

    def test_exactly_60(self):
        assert LutronTelnetConnection._seconds_to_lip_time(60) == "00:01:00"

    def test_minutes(self):
        assert LutronTelnetConnection._seconds_to_lip_time(90) == "00:01:30"
        assert LutronTelnetConnection._seconds_to_lip_time(1800) == "00:30:00"

    def test_hours(self):
        assert LutronTelnetConnection._seconds_to_lip_time(3600) == "01:00:00"
        assert LutronTelnetConnection._seconds_to_lip_time(14400) == "04:00:00"

    def test_mixed(self):
        assert LutronTelnetConnection._seconds_to_lip_time(3661) == "01:01:01"


class TestSetLightLevel:
    @pytest.mark.asyncio
    async def test_correct_command_format(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00") as mock_send:
            await conn.set_light_level(zone_id=25, brightness=50, fade_time=1800)
        mock_send.assert_called_once_with("#OUTPUT,25,1,50,00:30:00")

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
        mock_send.assert_called_once_with("#OUTPUT,25,1,50,00:00:00")

    @pytest.mark.asyncio
    async def test_under_60s_uses_seconds_field(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00") as mock_send:
            await conn.set_light_level(25, 50, 10)
        mock_send.assert_called_once_with("#OUTPUT,25,1,50,00:00:10")

    @pytest.mark.asyncio
    async def test_60s_formats_as_minutes(self):
        conn = make_connection()
        with patch.object(conn, 'send_command', return_value="~OUTPUT,25,1,50.00") as mock_send:
            await conn.set_light_level(25, 50, 60)
        mock_send.assert_called_once_with("#OUTPUT,25,1,50,00:01:00")


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
