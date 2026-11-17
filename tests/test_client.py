"""Client behavior against the emulated MX119."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial.capture import Event
from mcintosh_serial.client import Timing, ZonedClient
from mcintosh_serial.errors import (
    McIntoshCommandError,
    McIntoshConnectionError,
    McIntoshTimeoutError,
)
from mcintosh_serial.testing import FakeMX119, ReplayTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from mcintosh_serial.dialects.zoned import DeviceState

FAST = Timing(
    command=0.5, query=1.0, power=2.0, settle=0.05, settle_max=0.5, retry_delay=0.02
)


@pytest.fixture
async def rig() -> AsyncIterator[tuple[FakeMX119, ZonedClient]]:
    device = FakeMX119(time_scale=0.01)
    client = ZonedClient(device, FAST)
    yield device, client
    await client.stop()


async def test_start_enables_rs232_when_first_query_is_rejected(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    assert not device.rs232_enabled
    await client.start()
    assert device.rs232_enabled
    assert client.state.zone(1).power is True
    assert client.state.zone(1).volume == 8
    assert client.state.zone(2).muted is True


async def test_start_does_not_resend_ctl_when_already_enabled(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    device.rs232_enabled = True
    await client.start()
    assert client.state.zone(1).input == 3


async def test_volume_and_mute(rig: tuple[FakeMX119, ZonedClient]) -> None:
    device, client = rig
    await client.start()
    await client.set_volume(1, 5)
    await client.volume_step(1, up=True)
    assert device.volume[1] == 6
    assert client.state.zone(1).volume == 6
    await client.set_mute(1, muted=True)
    assert client.state.zone(1).muted is True
    await client.set_mute(1, muted=False)
    assert client.state.zone(1).muted is False


async def test_input_change_ends_unmuted_on_new_input(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    _, client = rig
    await client.start()
    await client.select_input(1, 4)
    await asyncio.sleep(0.1)
    assert client.state.zone(1).input == 4
    assert client.state.zone(1).muted is False


async def test_power_off_and_on(rig: tuple[FakeMX119, ZonedClient]) -> None:
    _, client = rig
    await client.start()
    await client.set_power(1, on=False)
    assert client.state.zone(1).power is False
    await client.set_power(1, on=True)
    await asyncio.sleep(0.2)
    assert client.state.zone(1).power is True
    assert client.state.zone(1).muted is False


async def test_front_panel_changes_reach_listeners(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    await client.start()
    seen: list[DeviceState] = []
    client.add_listener(seen.append)
    await device.front_panel_volume(1, 3)
    await asyncio.sleep(0.05)
    assert [s.zone(1).volume for s in seen] == [3]


async def test_query_retries_once_after_transient_error(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    device.rs232_enabled = True
    device.reject_next_query = True
    await client.start()  # first (QRY) is rejected, retry succeeds, no (CTL 1) needed
    assert client.state.zone(1).volume == 8


async def test_rapid_commands_all_succeed_because_client_paces_them(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    await client.start()
    await asyncio.gather(
        client.set_volume(1, 4),
        client.set_mute(1, muted=True),
        client.volume_step(1, up=True),
        client.query(),
    )
    assert device.dropped == []
    assert client.state.zone(1).volume == 5


async def test_out_of_range_input_times_out(rig: tuple[FakeMX119, ZonedClient]) -> None:
    _, client = rig
    await client.start()
    with pytest.raises(McIntoshTimeoutError):
        await client.select_input(1, 9)


async def test_invalid_zone_is_a_command_error(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    _, client = rig
    await client.start()
    with pytest.raises(McIntoshCommandError) as info:
        await client.set_volume(9, 3)
    assert info.value.code == "3"


async def test_power_cycle_nul_byte_is_harmless(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    await client.start()
    await device.power_cycle()
    await asyncio.sleep(0.05)
    await client.query()
    assert client.state.zone(1).power is False


async def test_connection_listener_reports_loss(
    rig: tuple[FakeMX119, ZonedClient],
) -> None:
    device, client = rig
    events: list[bool] = []
    client.add_connection_listener(events.append)
    await client.start()
    assert client.connected
    await device.close()  # transport EOF
    await asyncio.sleep(0.05)
    assert events == [True, False]
    assert not client.connected


class ScriptedTransport:
    """A transport whose replies come from a function, for cases the emulator can't."""

    def __init__(
        self, reply: Callable[[str], list[str]], *, fail_writes: bool = False
    ) -> None:
        self._reply = reply
        self._fail_writes = fail_writes
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def read(self) -> bytes:
        return await self.queue.get()

    async def write(self, data: bytes) -> None:
        if self._fail_writes:
            message = "port vanished"
            raise OSError(message)
        for chunk in self._reply(data.decode()):
            await self.queue.put(chunk.encode())

    async def close(self) -> None:
        await self.queue.put(b"")


async def test_listeners_can_be_removed() -> None:
    device = FakeMX119(rs232_enabled=True)
    client = ZonedClient(device, FAST)
    states: list[DeviceState] = []
    connections: list[bool] = []
    remove_state = client.add_listener(states.append)
    remove_connection = client.add_connection_listener(connections.append)
    remove_state()
    remove_connection()
    await client.start()
    await device.front_panel_volume(1, 2)
    await asyncio.sleep(0.05)
    await client.stop()
    assert states == []
    assert connections == []


async def test_stop_before_start_is_safe() -> None:
    client = ZonedClient(FakeMX119(), FAST)
    await client.stop()
    assert not client.connected


async def test_query_error_other_than_err_1_is_raised() -> None:
    client = ZonedClient(ScriptedTransport(lambda _data: ["(ERR 3)\r\n"]), FAST)
    with pytest.raises(McIntoshCommandError) as info:
        await client.start()
    assert info.value.code == "3"
    await client.stop()


async def test_bare_err_frame_has_unknown_code() -> None:
    client = ZonedClient(ScriptedTransport(lambda _data: ["(ERR)\r\n"]), FAST)
    with pytest.raises(McIntoshCommandError) as info:
        await client.start()
    assert info.value.code == "?"
    await client.stop()


async def test_write_failure_is_a_connection_error() -> None:
    client = ZonedClient(ScriptedTransport(lambda _data: [], fail_writes=True), FAST)
    with pytest.raises(McIntoshConnectionError):
        await client.start()
    await client.stop()


async def test_connection_lost_mid_command_fails_the_command() -> None:
    transport = ScriptedTransport(lambda _data: [])
    client = ZonedClient(transport, FAST)
    task = asyncio.ensure_future(client.start())
    await asyncio.sleep(0.05)
    await transport.close()
    with pytest.raises(McIntoshConnectionError):
        await task
    await client.stop()


async def test_settle_gives_up_after_the_maximum_wait() -> None:
    """A unit that never goes quiet must not block the next command forever."""
    timing = Timing(command=0.5, query=1.0, settle=0.05, settle_max=0.1)
    transport = ScriptedTransport(lambda _data: ["(PON Z1)\r\n"])
    client = ZonedClient(transport, timing)

    async def chatter() -> None:
        while True:
            await transport.queue.put(b"(MOD Z1 5)\r\n")
            await asyncio.sleep(0.01)

    task = asyncio.ensure_future(chatter())
    await client.start()
    task.cancel()
    await client.stop()


async def test_unsolicited_error_frame_is_ignored() -> None:
    device = FakeMX119(rs232_enabled=True)
    client = ZonedClient(device, FAST)
    await client.start()
    await device._out.put(b"(ERR 1)\r\n")  # nothing is pending
    await asyncio.sleep(0.05)
    assert client.connected
    await client.stop()


async def test_zero_settle_time_releases_the_next_command_immediately() -> None:
    transport = ScriptedTransport(lambda _data: ["(PON Z1)\r\n"])
    client = ZonedClient(transport, Timing(command=0.5, query=1.0, settle=0.0))
    await client.start()
    assert client.state.zone(1).power is True
    await client.stop()


async def test_start_works_for_a_unit_whose_status_dump_does_not_start_with_power() -> (
    None
):
    # Hypothetical: the C2500 may leave power out of its (QRY) reply; nothing confirms either way.
    unit = ReplayTransport(
        (
            Event("tx", "(QRY)"),
            Event("rx", "(INP Z1 3)\r\n(VST Z1 8)\r\n(MUT Z1 0)\r\n"),
        )
    )
    client = ZonedClient(unit, FAST)
    await client.start()
    assert client.state.zone(1).volume == 8
    assert client.state.zone(1).power is None  # not reported, so not guessed
    await client.stop()
