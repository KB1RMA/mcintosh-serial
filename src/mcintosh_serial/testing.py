"""In-process emulation of an MX119, for tests of this library and of integrations.

Behavior is copied from traffic captured on a real unit (docs/protocols/zoned.md):
RS232 must be enabled with (CTL 1), replies and pushes match, the unit mutes itself
around input and power changes, and commands that arrive while it is still talking
are dropped.
"""

import asyncio
from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine

_COMMAND_RE = re.compile(r"\(([^()]*)\)")
_ZONE_RE = re.compile(r"^Z(\d)$")
_VALID_INPUTS = range(8)
_ZONES = (1, 2)
_KNOWN = frozenset({"QRY", "PON", "POF", "VUP", "VDN", "VST", "MUT", "INP"})
_POWER_UP_DELAY = 0.6  # seconds the real unit stays quiet before its first dump
_SECOND_DUMP_DELAY = 5.0  # seconds before the second dump after power-on
_LINE_GAP = 0.03  # seconds between lines of a status dump


@dataclass(slots=True)
class FakeMX119:
    """A fake MX119 that implements the client's transport interface.

    ``time_scale`` multiplies every delay the real unit shows, so tests stay fast.
    """

    time_scale: float = 0.01
    rs232_enabled: bool = False
    powered: dict[int, bool] = field(default_factory=lambda: {1: True, 2: False})
    input: dict[int, int] = field(default_factory=lambda: {1: 3, 2: 3})
    volume: dict[int, int] = field(default_factory=lambda: {1: 8, 2: 20})
    muted: dict[int, bool] = field(default_factory=lambda: {1: False, 2: True})
    reject_next_query: bool = False  # simulate (ERR 1) right after power-up
    dropped: list[str] = field(default_factory=list[str])
    _out: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue[bytes])
    _in: str = ""
    _busy: bool = False
    _tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])

    # ---------------------------------------------------------------- wire
    async def read(self) -> bytes:
        """Return the next bytes the unit sends; ``b""`` after close."""
        return await self._out.get()

    async def write(self, data: bytes) -> None:
        """Accept bytes from the client and run each complete command."""
        self._in += data.decode("ascii", errors="ignore")
        commands = _COMMAND_RE.findall(self._in)
        if commands:
            self._in = self._in[self._in.rfind(")") + 1 :]
        for command in commands:
            self._spawn(self._handle(command))

    async def close(self) -> None:
        """Cancel anything the unit was still going to send, then signal EOF."""
        pending = tuple(self._tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._busy = False
        await self._out.put(b"")

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.time_scale)

    async def _emit(self, *lines: str, gap: float = 0.0) -> None:
        for line in lines:
            await self._out.put(f"({line})\r\n".encode("ascii"))
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
    async def _handle(self, payload: str) -> None:
        if self._busy:
            self.dropped.append(payload)
            return
        self._busy = True
        try:
            await self._dispatch(payload.split())
        finally:
            self._busy = False

    async def _dispatch(self, tokens: list[str]) -> None:
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
