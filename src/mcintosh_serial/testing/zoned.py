"""In-process emulation of an MX119 (the zoned dialect), built from traffic captured on a real unit.

Behavior is copied from docs/protocols/zoned.md: RS232 must be enabled with (CTL 1),
replies and pushes match, the unit mutes itself around input and power changes, and
commands that arrive while it is still talking are dropped.
"""

import re
from typing import override

from mcintosh_serial.testing._base import FakeUnit

_COMMAND_RE = re.compile(r"\(([^()]*)\)")
_ZONE_RE = re.compile(r"^Z(\d)$")
_VALID_INPUTS = range(8)
_ZONES = (1, 2)
_KNOWN = frozenset({"QRY", "PON", "POF", "VUP", "VDN", "VST", "MUT", "INP"})
_POWER_UP_DELAY = 0.6  # seconds the real unit stays quiet before its first dump
_SECOND_DUMP_DELAY = 5.0  # seconds before the second dump after power-on
_LINE_GAP = 0.03  # seconds between lines of a status dump


class FakeMX119(FakeUnit):
    """A fake MX119 that implements the client's transport interface."""

    def __init__(
        self, time_scale: float = 0.01, *, rs232_enabled: bool = False
    ) -> None:
        super().__init__(time_scale)
        self.rs232_enabled = rs232_enabled
        self.powered = {1: True, 2: False}
        self.input = {1: 3, 2: 3}
        self.volume = {1: 8, 2: 20}
        self.muted = {1: False, 2: True}
        self.reject_next_query = False  # simulate (ERR 1) right after power-up

    @override
    def _split(self, text: str) -> tuple[list[str], str]:
        commands = _COMMAND_RE.findall(text)
        return commands, text[text.rfind(")") + 1 :] if commands else text

    async def _emit(self, *lines: str, gap: float = 0.0) -> None:
        for line in lines:
            await self._emit_raw(f"({line})\r\n")
            await self._sleep(gap)

    # --------------------------------------------------------------- state
    def _dump(self) -> list[str]:
        def power(zone: int) -> str:
            return f"{'PON' if self.powered[zone] else 'POF'} Z{zone}"

        return [
            power(1),
            power(2),
            f"INP Z1 {self.input[1]}",
            f"INP Z2 {self.input[2]}",
            f"VST Z1 {self.volume[1]}",
            f"VST Z2 {self.volume[2]}",
            f"MUT Z1 {int(self.muted[1])}",
            f"MUT Z2 {int(self.muted[2])}",
            "MOD Z1 5",
            "TRS Z1 1 0",
            "TRS Z1 6 70",
            "TRS Z1 9 20",
        ]

    async def _send_dump(self) -> None:
        await self._emit(*self._dump(), gap=_LINE_GAP)

    # ------------------------------------------------- front-panel actions
    async def front_panel_volume(self, zone: int, level: int) -> None:
        """Simulate turning the volume knob: the unit pushes the new level."""
        self.volume[zone] = level
        await self._emit(f"VST Z{zone} {level}")

    async def power_cycle(self) -> None:
        """Mains off and on: back in standby, a stray NUL byte, RS232 still enabled."""
        self.powered = {1: False, 2: False}
        await self._out.put(b"\x00")

    # ------------------------------------------------------------ commands
    @override
    async def _dispatch(self, command: str) -> None:
        await self._dispatch_tokens(command.split())

    async def _dispatch_tokens(self, tokens: list[str]) -> None:
        name, args = (tokens[0].upper(), tokens[1:]) if tokens else ("", [])
        if name == "CTL" and args in (["0"], ["1"]):
            self.rs232_enabled = args == ["1"]
            await self._emit(f"CTL {args[0]}")
        elif not self.rs232_enabled or name not in _KNOWN:
            await self._emit("ERR 1")
        elif name == "QRY":
            await self._query()
        else:
            await self._zone_command(name, args)

    async def _query(self) -> None:
        if self.reject_next_query:
            self.reject_next_query = False
            await self._emit("ERR 1")
        else:
            await self._send_dump()

    async def _zone_command(self, name: str, args: list[str]) -> None:
        match = _ZONE_RE.match(args[0]) if args else None
        zone = int(match.group(1)) if match else 0
        if zone not in _ZONES:
            await self._emit("ERR 3")
        elif name in ("PON", "POF"):
            await self._power(zone, on=name == "PON")
        elif name in ("VUP", "VDN", "VST"):
            await self._volume(name, zone, args[1:])
        elif name == "MUT" and args[1:] in (["0"], ["1"]):
            self.muted[zone] = args[1] == "1"
            await self._emit(f"MUT Z{zone} {args[1]}")
        elif name == "INP" and args[1:2] and args[1].isdigit():
            await self._input(zone, int(args[1]))
        # otherwise, as on the real unit, malformed parameters get no reply

    async def _power(self, zone: int, *, on: bool) -> None:
        self.powered[zone] = on
        await self._emit(f"MUT Z{zone} 1")
        if not on:
            await self._emit(f"POF Z{zone}")
            return
        await self._sleep(_POWER_UP_DELAY)
        await self._send_dump()
        await self._sleep(_SECOND_DUMP_DELAY)
        await self._send_dump()
        await self._emit(f"MUT Z{zone} {int(self.muted[zone])}")

    async def _volume(self, name: str, zone: int, params: list[str]) -> None:
        if name == "VST" and params and params[0].isdigit():
            self.volume[zone] = int(params[0])
        elif name != "VST":
            self.volume[zone] += 1 if name == "VUP" else -1
        await self._emit(f"VST Z{zone} {self.volume[zone]}")

    async def _input(self, zone: int, number: int) -> None:
        if number not in _VALID_INPUTS:
            return  # the real unit ignores inputs 8 and up
        self.input[zone] = number
        await self._emit(f"MUT Z{zone} 1")
        await self._send_dump()
        await self._send_dump()
        await self._emit(f"MUT Z{zone} {int(self.muted[zone])}")
