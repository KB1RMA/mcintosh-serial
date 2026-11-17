"""The simple dialect (MA352, MA5300) against its emulator and as pure functions."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial import (
    Client,
    DeviceState,
    McIntoshCommandError,
    McIntoshTimeoutError,
    Timing,
    parse_frames,
)
from mcintosh_serial.dialects.simple import SimpleDialect
from mcintosh_serial.testing import FakeMA352

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

FAST = Timing(command=0.5, query=1.0, power=3.0, settle=0.05, settle_max=0.5)
DIALECT = SimpleDialect()


def apply(text: str, state: DeviceState | None = None) -> DeviceState:
    frames, _ = parse_frames(text)
    result = state or DeviceState()
    for frame in frames:
        result = DIALECT.apply(result, frame)
    return result


@pytest.fixture
async def rig() -> AsyncIterator[tuple[FakeMA352, Client]]:
    device = FakeMA352(time_scale=0.01)
    client = Client(device, DIALECT, FAST)
    yield device, client
    await client.stop()


# ------------------------------------------------------------ pure functions
def test_status_frames_update_the_single_zone() -> None:
    state = apply("(PWR 1)\r\n(VOL 22)\r\n(MUT 0)\r\n(INP 3)\r\n(STA 1)\r\n")
    zone = state.zone(1)
    assert (zone.power, zone.volume, zone.muted, zone.input) == (True, 22, False, 3)
    assert state.status_push is True


def test_product_information_is_collected() -> None:
    state = apply("(MA352)\r\n(Serial Number: AHW0001)\r\n(FW Version: 1.07)\r\n")
    assert state.info.model == "MA352"
    assert state.info.serial_number == "AHW0001"
    assert state.info.firmware == "1.07"


def test_unknown_and_malformed_frames_change_nothing() -> None:
    assert (
        apply("(TBA -3)(PWR x)(MUT 7)(VOL abc)(STA 9)(Something else)") == DeviceState()
    )


def test_errors_carry_the_reason_text() -> None:
    frames, _ = parse_frames("(ERROR - Invalid Command)(ERROR)(PWR 1)")
    assert [DIALECT.error_code(f) for f in frames] == ["Invalid Command", "?", None]


def test_commands_end_with_a_carriage_return() -> None:
    assert DIALECT.power(1, on=True).payload == "(PWR 1)\r"
    assert DIALECT.volume_set(1, 25).payload == "(VOL 25)\r"
    assert DIALECT.volume_step(1, up=False).payload == "(VOL D)\r"
    assert DIALECT.mute(1, muted=True).payload == "(MUT 1)\r"
    assert DIALECT.select_input(1, 4).payload == "(INP 4)\r"
    assert DIALECT.query_commands()[0].payload == "(QRY)\r"


def test_only_zone_one_exists() -> None:
    with pytest.raises(ValueError, match="one zone"):
        DIALECT.volume_set(2, 10)


def test_a_volume_already_at_target_is_skipped() -> None:
    skip = DIALECT.volume_set(1, 22).skip_if
    assert skip is not None
    assert skip(apply("(VOL 22)"))
    assert not skip(apply("(VOL 30)"))
    assert not skip(DeviceState())


# ------------------------------------------------------------ against the unit
async def test_start_loads_state_without_touching_status_reporting(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    assert client.state.info.model == "MA352"
    assert (client.state.zone(1).power, client.state.zone(1).volume) == (True, 22)
    assert (
        "STA 1" not in device.received
    )  # already on, and the unit would not acknowledge it


async def test_start_turns_status_reporting_on_when_it_is_off(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    device.values["STA"] = 0
    await client.start()
    assert device.values["STA"] == 1
    assert client.state.status_push is True


async def test_status_reporting_is_turned_on_after_power_on_from_standby(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    device.values["PWR"], device.values["STA"] = 0, 0
    await client.start()
    assert client.state.status_push is None  # standby: (QRY) does not say
    assert "STA 1" not in device.received  # and the unit would refuse it
    await client.set_power(1, on=True)
    assert device.values["STA"] == 1
    await device.front_panel_volume(40)
    await asyncio.sleep(0.05)
    assert client.state.zone(1).volume == 40


async def test_power_on_leaves_status_reporting_alone_when_it_is_on(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    await client.set_power(1, on=False)
    await client.set_power(1, on=True)
    assert "STA 1" not in device.received


async def test_volume_ramps_and_the_client_waits_for_the_target(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    seen: list[int | None] = []
    client.add_listener(lambda state: seen.append(state.zone(1).volume))
    await client.set_volume(1, 25)
    assert device.values["VOL"] == 25
    assert seen == [23, 24, 25]  # every step is pushed


async def test_setting_the_current_volume_sends_nothing(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    before = len(device.received)
    await client.set_volume(1, 22)
    assert len(device.received) == before


async def test_relative_volume_input_and_mute(rig: tuple[FakeMA352, Client]) -> None:
    device, client = rig
    await client.start()
    await client.volume_step(1, up=True)
    await client.volume_step(1, up=False)
    await client.volume_step(1, up=False)
    assert device.values["VOL"] == 21
    await client.select_input(1, 4)
    await client.set_mute(1, muted=True)
    assert (client.state.zone(1).input, client.state.zone(1).muted) == (4, True)
    await client.set_mute(1, muted=True)  # muting twice is acknowledged again


async def test_standby_reports_only_product_information(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    device.values["PWR"] = 0
    await client.start()
    assert client.state.info.model == "MA352"
    assert client.state.zone(1).power is False
    assert client.state.zone(1).volume is None


async def test_commands_in_standby_are_rejected_with_the_unit_error(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    device.values["PWR"] = 0
    await client.start()
    with pytest.raises(McIntoshCommandError) as info:
        await client.set_volume(1, 30)
    assert info.value.code == "Invalid Command"


async def test_an_out_of_range_input_is_rejected(rig: tuple[FakeMA352, Client]) -> None:
    _, client = rig
    await client.start()
    with pytest.raises(McIntoshCommandError) as info:
        await client.select_input(1, 9)
    assert info.value.code == "Invalid Parameter"


async def test_power_off_and_on_with_the_boot_delay(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    await client.set_power(1, on=False)
    assert client.state.zone(1).power is False
    await client.set_power(1, on=True)
    await asyncio.sleep(0.3)  # the emulated unit stays quiet for a while after power-on
    assert client.state.zone(1).power is True
    assert device.values["MUT"] == 0


async def test_front_panel_volume_is_pushed(rig: tuple[FakeMA352, Client]) -> None:
    device, client = rig
    await client.start()
    await device.front_panel_volume(30)
    await asyncio.sleep(0.05)
    assert client.state.zone(1).volume == 30


async def test_front_panel_changes_are_silent_when_status_reporting_is_off(
    rig: tuple[FakeMA352, Client],
) -> None:
    device, client = rig
    await client.start()
    device.values["STA"] = 0
    await device.front_panel_volume(40)
    await asyncio.sleep(0.05)
    assert client.state.zone(1).volume == 22


async def talk(device: FakeMA352, text: str) -> str:
    """Send raw text to an emulator nobody else is reading, and return everything it answers."""
    await device.write(text.encode())
    await asyncio.sleep(0.1)
    received = b""
    while not device._out.empty():
        received += device._out.get_nowait()
    return received.decode()


async def test_queries_without_parameter_and_a_bad_power_parameter() -> None:
    device = FakeMA352()
    assert "(VOL 22)" in await talk(device, "(VOL)")
    assert "(PWR 1)" in await talk(device, "(PWR)")
    assert "(ERROR - Invalid Parameter)" in await talk(device, "(PWR 5)")
    assert "(ERROR - Invalid Command)" in await talk(device, "()")
    assert await talk(device, "(VOL 22)") == ""  # unchanged volume is not acknowledged
    assert "(MUT 0)" in await talk(device, "(MUT 0)")  # unchanged mute is


class Scripted:
    """A transport answering from a function, for replies the emulator cannot produce."""

    def __init__(self, reply: Callable[[str], list[str]]) -> None:
        self._reply = reply
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def read(self) -> bytes:
        return await self.queue.get()

    async def write(self, data: bytes) -> None:
        for chunk in self._reply(data.decode()):
            await self.queue.put(chunk.encode())

    async def close(self) -> None:
        await self.queue.put(b"")


async def test_an_unacknowledged_status_enable_is_not_an_error() -> None:
    def reply(text: str) -> list[str]:
        return ["(MA352)\r\n", "(PWR 1)\r\n", "(STA 0)\r\n"] if "QRY" in text else []

    client = Client(
        Scripted(reply), DIALECT, Timing(command=0.1, query=0.5, settle=0.02)
    )
    await client.start()
    assert client.connected
    await client.stop()


async def test_a_refused_status_enable_is_not_an_error() -> None:
    def reply(text: str) -> list[str]:
        if "QRY" in text:
            return ["(MA352)\r\n", "(PWR 1)\r\n", "(STA 0)\r\n"]
        return ["(ERROR - Invalid Command)\r\n"]

    client = Client(
        Scripted(reply), DIALECT, Timing(command=0.1, query=0.5, settle=0.02)
    )
    await client.start()
    assert client.connected
    assert client.state.status_push is False
    await client.stop()


async def test_a_unit_that_never_answers_times_out() -> None:
    client = Client(Scripted(lambda _text: []), DIALECT, Timing(query=0.1, settle=0.02))
    with pytest.raises(McIntoshTimeoutError):
        await client.start()
    await client.stop()
