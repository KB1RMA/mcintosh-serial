"""The real serial transport, exercised over a pseudo-terminal."""

import asyncio
import os
import pty

from mcintosh_serial import StreamTransport, open_serial


async def test_open_serial_reads_and_writes_through_a_pty() -> None:
    master, slave = pty.openpty()
    transport = await open_serial(os.ttyname(slave), 9600)
    assert isinstance(transport, StreamTransport)
    os.write(master, b"(PON Z1)\r\n")
    assert await asyncio.wait_for(transport.read(), 2) == b"(PON Z1)\r\n"
    await transport.write(b"(QRY)")
    await asyncio.sleep(0.1)
    assert os.read(master, 64) == b"(QRY)"
    await transport.close()
    os.close(master)
    os.close(slave)
