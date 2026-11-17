"""Byte transports. The client only needs read/write/close, so tests can swap in a fake."""

import contextlib
from typing import TYPE_CHECKING, Protocol

import serialx

if TYPE_CHECKING:
    import asyncio

_READ_SIZE = 1024


class Transport(Protocol):
    """What the client needs from a byte stream."""

    async def read(self) -> bytes:
        """Return the next chunk of bytes; ``b""`` means the connection closed."""
        ...

    async def write(self, data: bytes) -> None:
        """Send bytes to the unit."""
        ...

    async def close(self) -> None:
        """Close the connection."""
        ...


class StreamTransport:
    """Transport over an asyncio stream pair (serial port, socket://, rfc2217://)."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read(self) -> bytes:
        """Return the next chunk of bytes; ``b""`` means the connection closed."""
        return await self._reader.read(_READ_SIZE)

    async def write(self, data: bytes) -> None:
        """Send bytes to the unit."""
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        """Close the connection."""
        self._writer.close()
        with contextlib.suppress(OSError):
            await self._writer.wait_closed()


async def open_serial(url: str, baudrate: int = 9600) -> StreamTransport:
    """Open a serial port by device path or URL, 8N1, no flow control.

    Uses ``serialx`` (the driver Home Assistant itself uses), so besides device paths
    it accepts ``socket://host:port`` and ``rfc2217://host:port`` URLs for network
    serial servers and, inside Home Assistant, ``esphome-hass://`` URLs for the serial
    ports of ESPHome devices such as the Home Assistant Connect AUX-2.
    """
    reader, writer = await serialx.open_serial_connection(url=url, baudrate=baudrate)
    return StreamTransport(reader, writer)
