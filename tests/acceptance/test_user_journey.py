"""User-journey tests that import the library only as an installed package.

CI runs these against the built wheel, so they use nothing but the public API: a
ZonedClient over a real serial transport (a pseudo-terminal) wired to the emulated unit.
"""

import asyncio
import contextlib
import os
import pty
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial import (
    DeviceState,
    McIntoshTimeoutError,
    Timing,
    ZonedClient,
    open_serial,
)
from mcintosh_serial.testing import FakeMX119

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

FAST = Timing(
    command=0.5, query=1.0, power=2.0, settle=0.05, settle_max=0.5, retry_delay=0.02
)


async def bridge(master: int, unit: FakeMX119) -> None:
    """Join the pty's far end to the emulated unit, like a serial cable."""
    loop = asyncio.get_running_loop()

    def to_unit() -> None:
        data = os.read(master, 256)
        loop.create_task(unit.write(data))  # noqa: RUF006 - short-lived, ends with the unit

    loop.add_reader(master, to_unit)
    try:
        while chunk := await unit.read():
            os.write(master, chunk)
    finally:
        loop.remove_reader(master)


@pytest.fixture
async def receiver() -> AsyncIterator[tuple[ZonedClient, FakeMX119]]:
    master, slave = pty.openpty()
    unit = FakeMX119(time_scale=0.01)
    cable = asyncio.ensure_future(bridge(master, unit))
    client = ZonedClient(await open_serial(os.ttyname(slave), 9600), FAST)
    yield client, unit
    await client.stop()
    cable.cancel()
    with contextlib.suppress(asyncio.CancelledError, OSError):
        await cable
    os.close(master)
    os.close(slave)


async def test_connect_reads_the_receiver_state(
    receiver: tuple[ZonedClient, FakeMX119],
) -> None:
    client, _unit = receiver
    await client.start()
    zone = client.state.zone(1)
    assert (zone.power, zone.input, zone.volume, zone.muted) == (True, 3, 8, False)
    assert client.state.zone(2).power is False


async def test_evening_listening_session(
    receiver: tuple[ZonedClient, FakeMX119],
) -> None:
    client, unit = receiver
    seen: list[DeviceState] = []
    await client.start()
    client.add_listener(seen.append)

    await client.select_input(1, 4)
    await client.set_volume(1, 12)
    await client.volume_step(1, up=False)
    await client.set_mute(1, muted=True)
    await client.set_mute(1, muted=False)
    await unit.front_panel_volume(1, 6)  # someone turns the knob
    await asyncio.sleep(0.2)

    zone = client.state.zone(1)
    assert (zone.input, zone.volume, zone.muted) == (4, 6, False)
    assert seen[-1] == client.state


async def test_power_off_then_on(receiver: tuple[ZonedClient, FakeMX119]) -> None:
    client, _unit = receiver
    await client.start()
    await client.set_power(1, on=False)
    assert client.state.zone(1).power is False
    await client.set_power(1, on=True)
    await asyncio.sleep(0.3)
    assert client.state.zone(1).power is True


async def test_an_input_the_receiver_ignores_times_out(
    receiver: tuple[ZonedClient, FakeMX119],
) -> None:
    client, _unit = receiver
    await client.start()
    with pytest.raises(McIntoshTimeoutError):
        await client.select_input(1, 9)
