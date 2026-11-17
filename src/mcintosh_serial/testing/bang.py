"""In-process emulation of an MX160-style processor (the bang dialect).

Modeled on the command names and query replies of the hass-mcintosh project. How a real
unit answers set commands and errors is not documented, so this emulator echoes the new
value (the most natural guess) and answers unknown commands with ``!ERR(1)``. Treat it
as an assumption, to be corrected the first time someone captures a real MX160.
"""

import re
from typing import override

from mcintosh_serial.testing._base import FakeUnit

_COMMAND_RE = re.compile(r"^!([A-Z]+)([+-]?)(?:\((\d+)\))?(\??)$")
_SECOND = 2
_SOURCES = {0: "HDMI 1", 1: "HDMI 2", 2: "HDMI 3", 3: "HDMI 4"}


class FakeMX160(FakeUnit):
    """A fake MX160 that implements the client's transport interface."""

    drops_when_busy = False

    def __init__(self, time_scale: float = 0.01) -> None:
        super().__init__(time_scale)
        self.power = {1: True}
        self.volume = {1: 40, 2: 25}
        self.muted = {1: False, 2: False}
        self.source = {1: 1, 2: 0}
        self.received: list[str] = []

    @override
    def _split(self, text: str) -> tuple[list[str], str]:
        *lines, rest = re.split(r"[\r\n]+", text)
        return [line for line in lines if line], rest

    async def _emit(self, line: str) -> None:
        await self._emit_raw(f"{line}\r")

    def _source_line(self, prefix: str, zone: int) -> str:
        number = self.source[zone]
        return f'!{prefix}({number}) "{_SOURCES.get(number, "Input")}"'

    # ------------------------------------------------- front-panel actions
    async def front_panel_volume(self, level: int) -> None:
        """Simulate turning the knob; the unit reports the new level."""
        self.volume[1] = level
        await self._emit(f"!VOL({level})")

    # ------------------------------------------------------------ commands
    @override
    async def _dispatch(self, command: str) -> None:
        self.received.append(command)
        match = _COMMAND_RE.match(command.strip())
        if match is None:
            await self._emit("!ERR(1)")
            return
        name, sign, value, query = match.groups()
        zone = _SECOND if name.startswith("Z") else 1
        base = name.removeprefix("Z") if zone == _SECOND else name
        if name == "PING":
            await self._emit("!PONG")
        elif name == "DEVICE":
            await self._emit("!DEVICE(MX160)")
        elif name == "VERB":
            await self._emit(f"!VERB({value})")
        elif name in ("PON", "POFF"):
            self.power[1] = name == "PON"
            await self._emit(f"!POWER({int(self.power[1])})")
        elif name == "POWER":
            await self._emit(f"!POWER({int(self.power[1])})")
        elif base in ("VOL", "MUTE", "MUTEON", "MUTEOFF", "SRC"):
            await self._zone_command(zone, base, sign, value, query)
        else:
            await self._emit("!ERR(1)")

    async def _zone_command(
        self, zone: int, base: str, sign: str, value: str | None, query: str
    ) -> None:
        prefix = "Z" if zone == _SECOND else ""
        if base == "VOL":
            if value is not None and not sign:
                self.volume[zone] = int(value)
            elif sign:
                self.volume[zone] += 1 if sign == "+" else -1
            await self._emit(f"!{prefix}VOL({self.volume[zone]})")
        elif base in ("MUTEON", "MUTEOFF"):
            self.muted[zone] = base == "MUTEON"
            await self._emit(f"!{prefix}MUTE({int(self.muted[zone])})")
        elif base == "MUTE":
            await self._emit(f"!{prefix}MUTE({int(self.muted[zone])})")
        else:
            if value is not None and not query:
                self.source[zone] = int(value)
            await self._emit(self._source_line(f"{prefix}SRC", zone))
