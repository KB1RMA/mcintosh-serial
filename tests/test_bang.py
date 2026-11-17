"""The bang dialect (MX160 family) against its emulator and as pure functions."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial import (
    Client,
    DeviceState,
    McIntoshCommandError,
    McIntoshTimeoutError,
    Timing,
)
from mcintosh_serial.dialects.bang import BangDialect
from mcintosh_serial.testing import FakeMX160

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

FAST = Timing(command=0.3, query=0.5, power=1.0, settle=0.03, settle_max=0.3)
DIALECT = BangDialect()


def apply(text: str, state: DeviceState | None = None) -> DeviceState:
    frames, rest = DIALECT.feed("", text)
    assert rest == ""
    result = state or DeviceState()
    for frame in frames:
        result = DIALECT.apply(result, frame)
    return result


@pytest.fixture
async def rig() -> AsyncIterator[tuple[FakeMX160, Client]]:
    device = FakeMX160(time_scale=0.01)
    client = Client(device, DIALECT, FAST)
    yield device, client
    await client.stop()


# ------------------------------------------------------------ pure functions
def test_reply_lines_update_both_zones() -> None:
    state = apply(
        '!POWER(1)\r!VOL(40)\r!MUTE(0)\r!SRC(1) "HDMI 2"\r!ZVOL(25)\r!ZMUTE(1)\r!ZSRC(0) "HDMI 1"\r'
    )
    main, second = state.zone(1), state.zone(2)
    assert (main.power, main.volume, main.muted, main.input) == (True, 40, False, 1)
    assert (second.volume, second.muted, second.input) == (25, True, 0)


def test_the_device_name_is_collected() -> None:
    assert apply("!DEVICE(MX160)\r").info.model == "MX160"


def test_unknown_and_malformed_lines_change_nothing() -> None:
    assert apply("!PONG\r!VOL(loud)\r!VOL\rhello\r!SOMETHING(5)\r") == DeviceState()


def test_a_partial_line_waits_for_its_end() -> None:
    frames, rest = DIALECT.feed("", "!VOL(4")
    assert (frames, rest) == ((), "!VOL(4")
    frames, rest = DIALECT.feed(rest, "0)\r\n!MU")
    assert [f.name for f in frames] == ["VOL"]
    assert rest == "!MU"


def test_error_lines_are_recognized() -> None:
    frames, _ = DIALECT.feed("", "!ERR(7)\r!ERR\r!POWER(1)\r")
    assert [DIALECT.error_code(f) for f in frames] == ["7", "ERR", None]


def test_command_text_for_each_zone() -> None:
    assert DIALECT.power(1, on=True).payload == "!PON\r"
    assert DIALECT.power(1, on=False).payload == "!POFF\r"
    assert DIALECT.volume_set(1, 30).payload == "!VOL(30)\r"
    assert DIALECT.volume_set(2, 30).payload == "!ZVOL(30)\r"
    assert DIALECT.volume_step(1, up=True).payload == "!VOL+\r"
    assert DIALECT.volume_step(2, up=False).payload == "!ZVOL-\r"
    assert DIALECT.mute(1, muted=True).payload == "!MUTEON\r"
    assert DIALECT.mute(2, muted=False).payload == "!ZMUTEOFF\r"
    assert DIALECT.select_input(1, 3).payload == "!SRC(3)\r"
    assert DIALECT.select_input(2, 3).payload == "!ZSRC(3)\r"
    assert DIALECT.probe().payload == "!PING?\r"


def test_zone_two_power_and_unknown_zones_are_refused() -> None:
    with pytest.raises(ValueError, match="zone 2 power"):
        DIALECT.power(2, on=True)
    with pytest.raises(ValueError, match="zones 1 and 2"):
        DIALECT.volume_set(3, 10)


# ------------------------------------------------------------ against the unit
async def test_start_loads_both_zones_and_the_device_name(
    rig: tuple[FakeMX160, Client],
) -> None:
    device, client = rig
    await client.start()
    assert client.state.info.model == "MX160"
    assert client.state.zone(1).volume == 40
    assert client.state.zone(2).input == 0
    assert "!VERB(2)" in device.received


async def test_every_control_for_both_zones(rig: tuple[FakeMX160, Client]) -> None:
    device, client = rig
    await client.start()
    await client.set_power(1, on=False)
    await client.set_power(1, on=True)
    await client.set_volume(1, 50)
    await client.volume_step(1, up=True)
    await client.set_mute(1, muted=True)
    await client.select_input(1, 3)
    await client.set_volume(2, 10)
    await client.volume_step(2, up=False)
    await client.set_mute(2, muted=True)
    await client.select_input(2, 2)
    assert device.power[1] is True
    assert (device.volume[1], device.muted[1], device.source[1]) == (51, True, 3)
    assert (device.volume[2], device.muted[2], device.source[2]) == (9, True, 2)
    assert client.state.zone(2).volume == 9


async def test_front_panel_volume_is_pushed(rig: tuple[FakeMX160, Client]) -> None:
    device, client = rig
    await client.start()
    await device.front_panel_volume(33)
    await asyncio.sleep(0.05)
    assert client.state.zone(1).volume == 33


async def test_probe_gets_a_pong(rig: tuple[FakeMX160, Client]) -> None:
    _, client = rig
    await client.start()
    frame = await client.exchange(DIALECT.probe())
    assert frame.name == "PONG"


async def test_the_emulator_answers_each_query_and_rejects_unknown_commands() -> None:
    device = FakeMX160()
    for command, expected in (
        ("!POWER?", "!POWER(1)"),
        ("!MUTE?", "!MUTE(0)"),
        ("!ZMUTE?", "!ZMUTE(0)"),
        ("!SRC?", '!SRC(1) "HDMI 2"'),
        ("!SRC(9)", '!SRC(9) "Input"'),
        ("!ZSRC?", '!ZSRC(0) "HDMI 1"'),
        ("!VOL?", "!VOL(40)"),
        ("!NOPE", "!ERR(1)"),
        ("garbage", "!ERR(1)"),
    ):
        await device.write(command.encode() + b"\r")
        assert (await asyncio.wait_for(device.read(), 1)).decode().strip() == expected


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


async def test_a_unit_that_ignores_the_optional_commands_still_starts() -> None:
    def reply(text: str) -> list[str]:
        return ["!POWER(1)\r"] if "POWER?" in text else []

    client = Client(
        Scripted(reply), DIALECT, Timing(command=0.05, query=0.05, settle=0.01)
    )
    await client.start()
    assert client.state.zone(1).power is True
    await client.stop()


async def test_a_rejected_optional_query_is_tolerated_but_a_rejected_power_query_is_not() -> (
    None
):
    def tolerant(text: str) -> list[str]:
        return ["!POWER(1)\r"] if "POWER?" in text else ["!ERR(5)\r"]

    client = Client(
        Scripted(tolerant), DIALECT, Timing(command=0.05, query=0.1, settle=0.01)
    )
    await client.start()
    await client.stop()

    strict = Client(
        Scripted(lambda _text: ["!ERR(5)\r"]), DIALECT, Timing(query=0.1, settle=0.01)
    )
    with pytest.raises(McIntoshCommandError):
        await strict.start()
    await strict.stop()


async def test_a_silent_unit_times_out_on_the_required_query() -> None:
    client = Client(
        Scripted(lambda _text: []),
        DIALECT,
        Timing(command=0.05, query=0.05, settle=0.01),
    )
    with pytest.raises(McIntoshTimeoutError):
        await client.start()
    await client.stop()
