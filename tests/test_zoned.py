"""Tests built from traffic captured on a real MX119 (2026-11-16)."""

from __future__ import annotations

from mcintosh_serial.dialects import zoned
from mcintosh_serial.frames import parse_frames

# Reply to (QRY) with Zone 1 on / input 3 / volume 8 / unmuted, Zone 2 off / muted.
QRY_DUMP = (
    "(PON Z1)\r\n(POF Z2)\r\n(INP Z1 3)\r\n(INP Z2 3)\r\n(VST Z1 8)\r\n(VST Z2 20)\r\n"
    "(MUT Z1 0)\r\n(MUT Z2 1)\r\n(MOD Z1 5)\r\n(TRS Z1 1 0)\r\n(TRS Z1 6 70)\r\n"
)


def test_parse_full_dump() -> None:
    frames, rest = parse_frames(QRY_DUMP)
    assert rest == ""
    assert [f.name for f in frames][:4] == ["PON", "POF", "INP", "INP"]
    assert frames[0].args == ("Z1",)
    assert frames[4].args == ("Z1", "8")


def test_apply_dump_to_state() -> None:
    frames, _ = parse_frames(QRY_DUMP)
    state = zoned.apply_frames(zoned.DeviceState(), frames)
    assert state.zone(1) == zoned.ZoneState(power=True, input=3, volume=8, muted=False)
    assert state.zone(2) == zoned.ZoneState(power=False, input=3, volume=20, muted=True)


def test_split_chunks_reassemble() -> None:
    first, rest = parse_frames("(VST Z1 4)\r\n(VST Z")
    assert [f.name for f in first] == ["VST"]
    assert rest == "(VST Z"
    second, rest = parse_frames(rest + "1 5)\r\n")
    assert second[0].args == ("Z1", "5")
    assert rest == ""


def test_nul_bytes_and_leading_noise_are_ignored() -> None:
    frames, rest = parse_frames("\x00\x00junk(MUT Z1 1)\r\n")
    assert [f.name for f in frames] == ["MUT"]
    assert rest == ""


def test_tuner_frame_has_no_zone() -> None:
    frames, _ = parse_frames("(TNQ     87.50 FM  )\r\n")
    state = zoned.apply_frames(zoned.DeviceState(), frames)
    assert state.tuner == "87.50 FM"


def test_errors_do_not_change_state() -> None:
    frames, _ = parse_frames("(ERR 1)\r\n(ERR 3)\r\n")
    assert all(zoned.is_error(f) for f in frames)
    assert zoned.apply_frames(zoned.DeviceState(), frames) == zoned.DeviceState()


def test_malformed_values_are_ignored() -> None:
    frames, _ = parse_frames("(VST Z1 abc)(MUT Z1 7)(INP Z9)")
    assert zoned.apply_frames(zoned.DeviceState(), frames) == zoned.DeviceState()


def test_state_is_immutable_between_updates() -> None:
    before = zoned.DeviceState()
    frames, _ = parse_frames("(VST Z1 3)")
    after = zoned.apply_frames(before, frames)
    assert before.zones == {}
    assert after.zone(1).volume == 3


def test_command_encoding() -> None:
    assert zoned.enable_rs232() == "(CTL 1)"
    assert zoned.power(1, on=True) == "(PON Z1)"
    assert zoned.power(1, on=False) == "(POF Z1)"
    assert zoned.volume_step(1, up=True) == "(VUP Z1)"
    assert zoned.volume_set(1, 7) == "(VST Z1 7)"
    assert zoned.mute(1, muted=True) == "(MUT Z1 1)"
    assert zoned.select_input(1, 3) == "(INP Z1 3)"
