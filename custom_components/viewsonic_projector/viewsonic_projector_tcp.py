"""TCP connection for ViewSonic projector module (RS-232/LAN protocol).

Supported functions:
    * Power on / off / toggle / status
    * Input source selection / status
    * Mute on / off / status
    * Volume up / down / set / status
    * Operating temperature query
    * Light source usage time query
"""

import asyncio
from enum import IntEnum
import logging

_LOGGER = logging.getLogger(__name__)


# ====================================================================== #
# Local exceptions
# ====================================================================== #


class ProjectorError(Exception):
    """Base class for all ViewSonic projector errors."""


class ProjectorUnavailableError(ProjectorError):
    """Raised when the projector cannot be reached over TCP."""


class ProjectorTimeoutError(ProjectorUnavailableError):
    """Raised when the projector does not reply within the timeout."""


class ProjectorProtocolError(ProjectorError):
    """Raised when the projector returns an unexpected or malformed reply."""


# ====================================================================== #
# Protocol framing constants
# ====================================================================== #

VIEWSONIC_LAN_PORT = 4661
DEFAULT_TIMEOUT = 0.1

PACKET_TYPE_WRITE = 0x06
PACKET_TYPE_READ = 0x07
PACKET_TYPE_WRITE_RESPONSE = 0x03  # ACK for a write
PACKET_TYPE_READ_RESPONSE = 0x05  # Reply for a read

HEADER_BYTE_1 = 0x14
HEADER_COMMAND_MARKER = 0x34
FILLER_BYTE = 0x00

READ_RESPONSE_HEADER_LEN = 5
READ_RESPONSE_DATA_OFFSET = 7
READ_RESPONSE_MIN_LEN = 8


# ====================================================================== #
# Command table — each entry is a (cmd2, cmd3) tuple
# ====================================================================== #


class Command:
    """ViewSonic command identifiers as ``(cmd2, cmd3)`` tuples.

    Using a plain namespace class (not an enum) so the value is a real
    tuple that can be unpacked straight into the packet builders.
    """

    # --- Power (cmd2 = 0x11) ---
    POWER = (0x11, 0x00)  # ON / read status
    POWER_OFF = (0x11, 0x01)  # OFF
    POWER_TOGGLE = (0x11, 0x34)  # toggle

    # --- Input source (cmd2 = 0x13) ---
    SOURCE_INPUT = (0x13, 0x01)  # set / read

    # --- Mute / Volume (cmd2 = 0x14) ---
    MUTE = (0x14, 0x00)  # mute on/off + read status
    VOLUME_UP = (0x14, 0x01)
    VOLUME_DOWN = (0x14, 0x02)
    VOLUME_QUERY = (0x14, 0x03)
    VOLUME_VALUE = (0x14, 0x2A)

    # --- Info queries ---
    OPERATING_TEMP = (0x15, 0x03)  # command list no. 211
    LIGHT_SOURCE_USAGE = (0x15, 0x01)  # equivalent light-source hours


# ====================================================================== #
# Data byte values
# ====================================================================== #


class Action(IntEnum):
    """Data-byte values used by the supported commands."""

    OFF = 0x00
    ON = 0x01
    VOLUME_STEP = 0x01


class PowerStatus(IntEnum):
    """Values returned by reading Command.POWER."""

    OFF = 0x00
    ON = 0x01
    WARM_UP = 0x02
    COOL_DOWN = 0x03


class InputSource(IntEnum):
    """Values for Command.SOURCE_INPUT."""

    HDMI_1 = 0x00
    HDMI_2 = 0x01
    USB_C = 0x03


# ====================================================================== #
# Packet builders  (raw hex lives only here)
# ====================================================================== #


def _checksum(data: bytes) -> int:
    """Return the ViewSonic checksum for a packet.

    The checksum is the sum of all bytes except BYTE 0 (the packet
    type) and the checksum byte itself, taken modulo 256.
    """
    return sum(data[1:]) & 0xFF


def build_write_packet(command: tuple[int, int], data: bytes = b"") -> bytes:
    """Build a Write-Function packet from a (cmd2, cmd3) tuple + data."""
    cmd2, cmd3 = command
    payload = bytes([HEADER_COMMAND_MARKER, cmd2, cmd3]) + data
    length = len(payload)
    packet = (
        bytes(
            [
                PACKET_TYPE_WRITE,
                HEADER_BYTE_1,
                FILLER_BYTE,
                length & 0xFF,
                (length >> 8) & 0xFF,
            ]
        )
        + payload
    )
    return packet + bytes([_checksum(packet)])


def build_read_packet(command: tuple[int, int]) -> bytes:
    """Build a Read-Function packet from a (cmd2, cmd3) tuple."""
    cmd2, cmd3 = command
    payload = bytes(
        [
            HEADER_COMMAND_MARKER,
            FILLER_BYTE,
            FILLER_BYTE,
            cmd2,
            cmd3,
        ]
    )
    length = len(payload)
    packet = (
        bytes(
            [
                PACKET_TYPE_READ,
                HEADER_BYTE_1,
                FILLER_BYTE,
                length & 0xFF,
                (length >> 8) & 0xFF,
            ]
        )
        + payload
    )
    return packet + bytes([_checksum(packet)])


# ====================================================================== #
# Connector
# ====================================================================== #


class ViewSonicProjectorTCP:
    """ViewSonic TCP connector (power / input / mute / volume / info)."""

    def __init__(
        self,
        host: str,
        port: int = VIEWSONIC_LAN_PORT,
        password: str | None = None,
        on_imevent=None,
    ) -> None:
        """Initialise the connector.

        :param host:       IP address or hostname of the projector.
        :param port:       TCP port. Defaults to ``VIEWSONIC_LAN_PORT``.
        :param password:   Unused; kept for API compatibility.
        :param on_imevent: Unused; kept for API compatibility.
        """
        self._host = host
        self._port = port

        self._writer: asyncio.StreamWriter | None = None
        self._listener_task: asyncio.Task | None = None

        self._pending_request_future: asyncio.Future | None = None
        self._request_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def async_init(self) -> None:
        """Open the TCP connection to the projector and start the listener.

        :raises ProjectorUnavailableError: if the connection fails.
        """
        async with asyncio.timeout(DEFAULT_TIMEOUT):
            reader, self._writer = await asyncio.open_connection(self._host, self._port)
        self._listener_task = asyncio.create_task(
            self._listener_task_impl(reader, self._writer)
        )
        _LOGGER.info("Connection to %s:%s open", self._host, self._port)

    def close(self) -> None:
        """Cancel the listener task and close the TCP socket."""
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._writer:
            self._writer.close()
            self._writer = None

    # ------------------------------------------------------------------ #
    # Framing / listener
    # ------------------------------------------------------------------ #

    async def _read_packet(self, reader: asyncio.StreamReader) -> bytes | None:
        """Read one complete ViewSonic packet, or return ``None`` on EOF."""
        try:
            header = await reader.readexactly(READ_RESPONSE_HEADER_LEN)
        except asyncio.IncompleteReadError:
            return None
        length = header[3] | (header[4] << 8)
        try:
            rest = await reader.readexactly(length + 1)  # body + checksum
        except asyncio.IncompleteReadError:
            return None
        return header + rest

    async def _listener_task_impl(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Route incoming packets to the pending request future."""
        while not writer.is_closing():
            packet = await self._read_packet(reader)
            if packet is None:
                _LOGGER.debug("EOF reached on %s", self._host)
                writer.close()
                self._writer = None
                break

            _LOGGER.debug("Received packet: %s", packet.hex(" "))

            if _checksum(packet[:-1]) != packet[-1]:
                _LOGGER.warning("Bad checksum: %s", packet.hex(" "))
                continue

            future = self._pending_request_future
            if future is not None and not future.done():
                future.set_result(packet)
                continue

            _LOGGER.warning("Unsolicited packet: %s", packet.hex(" "))

    # ------------------------------------------------------------------ #
    # Request / response core
    # ------------------------------------------------------------------ #

    async def send_request(self, packet: bytes, timeout: float) -> bytes:
        """Send a raw, already-framed packet and return the raw reply.

        :raises ProjectorUnavailableError: if the socket is not connected.
        :raises ProjectorTimeoutError: if no reply arrives within ``timeout``.
        """
        if not self._writer or self._writer.is_closing():
            await self.async_init()
        if not self._writer:
            raise ProjectorUnavailableError(
                f"Not connected to {self._host}:{self._port}"
            )

        async with self._request_lock:
            pending: asyncio.Future | None = None
            try:
                async with asyncio.timeout(timeout):
                    loop = asyncio.get_running_loop()
                    pending = loop.create_future()
                    self._pending_request_future = pending

                    _LOGGER.debug("Sending packet: %s", packet.hex(" "))
                    self._writer.write(packet)
                    await self._writer.drain()

                    response: bytes = await pending
                    _LOGGER.debug("Response packet: %s", response.hex(" "))
                    return response
            except TimeoutError as e:
                _LOGGER.error("Timeout on %s", packet.hex(" "))
                raise ProjectorTimeoutError(
                    f"Timeout waiting for reply to {packet.hex(' ')}"
                ) from e
            finally:
                if pending is not None and not pending.done():
                    pending.cancel()
                self._pending_request_future = None

    @staticmethod
    def _parse_read_response(packet: bytes) -> bytes:
        """Extract the data payload from a Read Response packet.

        :raises ProjectorProtocolError: if the packet is malformed.
        """
        if (
            len(packet) < READ_RESPONSE_MIN_LEN
            or packet[0] != PACKET_TYPE_READ_RESPONSE
        ):
            raise ProjectorProtocolError(
                f"Not a valid read response: {packet.hex(' ')}"
            )
        length = packet[3] | (packet[4] << 8)
        return packet[READ_RESPONSE_DATA_OFFSET : READ_RESPONSE_HEADER_LEN + length]

    async def _send_command(
        self,
        command: tuple[int, int],
        data: bytes = b"",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Send a Write-Function command and verify the ACK.

        :raises ProjectorProtocolError: if the reply is not a write ACK.
        """
        packet = build_write_packet(command, data)
        response = await self.send_request(packet, timeout)
        if response[0] != PACKET_TYPE_WRITE_RESPONSE:
            _LOGGER.warning(
                "Unexpected response type 0x%02X for command 0x%02X/0x%02X",
                response[0],
                command[0],
                command[1],
            )
            raise ProjectorProtocolError(
                f"Unexpected response type 0x{response[0]:02X} for "
                f"command 0x{command[0]:02X}/0x{command[1]:02X}"
            )

    async def _get_property(
        self,
        command: tuple[int, int],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> int | bytes:
        """Send a Read-Function and return the payload.

        - single byte payload -> ``int``
        - multi-byte payload  -> ``bytes``

        :raises ProjectorProtocolError: if the reply is malformed or empty.
        """
        packet = build_read_packet(command)
        response = await self.send_request(packet, timeout)

        data = self._parse_read_response(response)
        if len(data) == 0:
            raise ProjectorProtocolError(
                f"Empty payload for read command 0x{command[0]:02X}/0x{command[1]:02X}"
            )
        if len(data) == 1:
            return data[0]
        return data

    # ================================================================== #
    # Power
    # ================================================================== #

    async def power_on(self) -> None:
        """Turn the projector on."""
        await self._send_command(Command.POWER, bytes([Action.OFF]))

    async def power_off(self) -> None:
        """Turn the projector off."""
        await self._send_command(Command.POWER_OFF, bytes([Action.OFF]))

    async def power_toggle(self) -> None:
        """Toggle the projector's power state."""
        await self._send_command(Command.POWER_TOGGLE, bytes([Action.OFF]))

    async def power_status(self) -> PowerStatus:
        """Return the current :class:`PowerStatus`.

        :raises ProjectorProtocolError: on a malformed or unknown reply.
        """
        value = await self._get_property(Command.POWER)
        if not isinstance(value, int):
            raise ProjectorProtocolError(f"Unexpected power payload: {value!r}")
        try:
            return PowerStatus(value)
        except ValueError as e:
            _LOGGER.warning("Unknown power state value: 0x%02X", value)
            raise ProjectorProtocolError(
                f"Unknown power state value: 0x{value:02X}"
            ) from e

    # ================================================================== #
    # Input source
    # ================================================================== #

    async def set_input(self, source: InputSource) -> None:
        """Select an input source."""
        await self._send_command(Command.SOURCE_INPUT, bytes([int(source)]))

    async def input_status(self) -> InputSource:
        """Return the currently selected :class:`InputSource`.

        :raises ProjectorProtocolError: on a malformed or unknown reply.
        """
        value = await self._get_property(Command.SOURCE_INPUT)
        if not isinstance(value, int):
            raise ProjectorProtocolError(f"Unexpected input source payload: {value!r}")
        try:
            return InputSource(value)
        except ValueError as e:
            _LOGGER.warning("Unknown input source value: 0x%02X", value)
            raise ProjectorProtocolError(
                f"Unknown input source value: 0x{value:02X}"
            ) from e

    # ================================================================== #
    # Mute
    # ================================================================== #

    async def mute_on(self) -> None:
        """Mute the projector's audio output."""
        await self._send_command(Command.MUTE, bytes([Action.ON]))

    async def mute_off(self) -> None:
        """Unmute the projector's audio output."""
        await self._send_command(Command.MUTE, bytes([Action.OFF]))

    async def mute_status(self) -> bool:
        """Return ``True`` if muted, ``False`` otherwise.

        :raises ProjectorProtocolError: on a malformed reply.
        """
        value = await self._get_property(Command.MUTE)
        if not isinstance(value, int):
            raise ProjectorProtocolError(f"Unexpected mute payload: {value!r}")
        return bool(value)

    # ================================================================== #
    # Volume
    # ================================================================== #

    async def volume_up(self) -> None:
        """Increase the volume by one step."""
        await self._send_command(Command.VOLUME_UP, bytes([Action.VOLUME_STEP]))

    async def volume_down(self) -> None:
        """Decrease the volume by one step."""
        await self._send_command(Command.VOLUME_DOWN, bytes([Action.VOLUME_STEP]))

    async def volume_set(self, value: int) -> None:
        """Set the volume to an absolute value (0-255 per the protocol)."""
        await self._send_command(Command.VOLUME_VALUE, bytes([value & 0xFF]))

    async def volume_status(self) -> int:
        """Return the current volume level (0-255).

        :raises ProjectorProtocolError: on a malformed reply.
        """
        value = await self._get_property(Command.VOLUME_QUERY)
        if not isinstance(value, int):
            raise ProjectorProtocolError(f"Unexpected volume payload: {value!r}")
        return value

    # ================================================================== #
    # Info queries
    # ================================================================== #

    async def get_operating_temperature(self) -> float:
        """Return the operating temperature in degrees Celsius.

        Per spec note 1, the response carries a little-endian ``uint32``
        whose value, divided by 10, is the temperature in degrees C.

        :raises ProjectorProtocolError: if the reply is too short.
        """
        data = await self._get_property(Command.OPERATING_TEMP)
        if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
            raise ProjectorProtocolError(
                f"Operating temperature payload too short: {data!r}"
            )
        return int.from_bytes(data[:4], "little") / 10.0

    async def get_light_source_usage_time(self) -> int:
        """Return the equivalent light-source usage time in hours.

        Per spec note 4, the response carries a little-endian ``uint32``
        of hours in BYTE 7..10 of the read response.

        :raises ProjectorProtocolError: if the reply is too short.
        """
        data = await self._get_property(Command.LIGHT_SOURCE_USAGE)
        if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
            raise ProjectorProtocolError(
                f"Light source usage payload too short: {data!r}"
            )
        return int.from_bytes(data[:4], "little")
