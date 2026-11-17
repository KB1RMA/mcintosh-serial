"""The emulated MX119 is public API (integrations test against it), so it is tested too."""

import asyncio

from mcintosh_serial import parse_frames
from mcintosh_serial.testing import FakeMX119


async def talk(device: FakeMX119, data: str, wait: float = 0.3) -> list[str]:
    """Send raw text, return the names and args of what comes back."""
    await device.write(data.encode())
    await asyncio.sleep(wait)
    received = b""
    while not device._out.empty():
        received += device._out.get_nowait()
    frames, _ = parse_frames(received.decode())
    return [" ".join((f.name, *f.args)) for f in frames]


async def test_rs232_must_be_enabled_first() -> None:
    device = FakeMX119()
    assert await talk(device, "(QRY)") == ["ERR 1"]
    assert await talk(device, "(CTL 1)") == ["CTL 1"]
    assert len(await talk(device, "(QRY)")) == 12
    assert await talk(device, "(CTL 0)") == ["CTL 0"]
    assert await talk(device, "(QRY)") == ["ERR 1"]


async def test_commands_are_case_insensitive_and_unknown_ones_are_rejected() -> None:
    device = FakeMX119(rs232_enabled=True)
    assert await talk(device, "(vst z1 5)") == ["ERR 3"]  # zone token is exact
    assert await talk(device, "(XXX)") == ["ERR 1"]
    assert await talk(device, "()") == ["ERR 1"]
    assert await talk(device, "(vst Z1 5)") == ["VST Z1 5"]


async def test_invalid_zone_is_err_3() -> None:
    device = FakeMX119(rs232_enabled=True)
    assert await talk(device, "(INP Z9 3)") == ["ERR 3"]
    assert await talk(device, "(INP)") == ["ERR 3"]


async def test_volume_steps_and_set() -> None:
    device = FakeMX119(rs232_enabled=True)
    assert await talk(device, "(VUP Z1)") == ["VST Z1 9"]
    assert await talk(device, "(VDN Z1)") == ["VST Z1 8"]
    assert await talk(device, "(VST Z1 abc)") == [
        "VST Z1 8"
    ]  # unparsable level keeps the volume


async def test_malformed_parameters_get_no_reply() -> None:
    device = FakeMX119(rs232_enabled=True)
    assert await talk(device, "(MUT Z1 7)") == []
    assert await talk(device, "(INP Z1 x)") == []
    assert await talk(device, "(INP Z1 9)") == []


async def test_commands_arriving_while_busy_are_dropped() -> None:
    device = FakeMX119(rs232_enabled=True, time_scale=0.1)
    await talk(device, "(QRY)(QRY)")
    assert device.dropped == ["QRY"]


async def test_partial_command_waits_for_its_closing_parenthesis() -> None:
    device = FakeMX119(rs232_enabled=True)
    assert await talk(device, "(QR") == []
    assert len(await talk(device, "Y)")) == 12


async def test_input_change_mutes_dumps_twice_then_restores_mute() -> None:
    device = FakeMX119(rs232_enabled=True)
    names = await talk(device, "(INP Z1 4)", wait=0.6)
    assert names[0] == "MUT Z1 1"
    assert names.count("PON Z1") == 2
    assert names[-1] == "MUT Z1 0"
    assert device.input[1] == 4


async def test_power_on_mutes_then_dumps_twice() -> None:
    device = FakeMX119(rs232_enabled=True, time_scale=0.01)
    await talk(device, "(POF Z1)")
    names = await talk(device, "(PON Z1)", wait=0.8)
    assert names[0] == "MUT Z1 1"
    assert names.count("PON Z1") == 2
    assert names[-1] == "MUT Z1 0"


async def test_power_cycle_keeps_rs232_and_returns_in_standby() -> None:
    device = FakeMX119(rs232_enabled=True)
    await device.power_cycle()
    assert await device.read() == b"\x00"
    assert (await talk(device, "(QRY)"))[0] == "POF Z1"


async def test_close_signals_eof() -> None:
    device = FakeMX119()
    await device.close()
    assert await device.read() == b""


async def test_close_cancels_replies_still_being_sent() -> None:
    device = FakeMX119(rs232_enabled=True, time_scale=1.0)
    await device.write(b"(QRY)")
    await asyncio.sleep(0.05)  # mid-dump
    await device.close()
    assert not device._tasks
