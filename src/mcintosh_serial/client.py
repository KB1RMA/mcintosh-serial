"""Async client for the zoned dialect.

One command is in flight at a time. After the expected reply arrives the client
waits for the line to go quiet before releasing the next command, because the
unit drops commands that arrive while it is still sending a reply.
"""

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING

from mcintosh_serial.dialects import zoned
from mcintosh_serial.errors import (
    McIntoshCommandError,
    McIntoshConnectionError,
    McIntoshTimeoutError,
)
from mcintosh_serial.frames import Frame, parse_frames

if TYPE_CHECKING:
    from mcintosh_serial.transport import Transport

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[zoned.DeviceState], None]
ConnectionListener = Callable[[bool], None]
Matcher = Callable[[Frame], bool]


@dataclass(frozen=True, slots=True)
class Timing:
    """Seconds. Defaults come from the MX119; override in tests."""

    command: float = 2.0
    query: float = 4.0
    power: float = 12.0
    settle: float = 0.3  # quiet time after a reply before the next command
    settle_max: float = 3.0
    retry_delay: float = 1.0  # wait before retrying a (QRY) rejected after power-up


@dataclass(slots=True)
class _Pending:
    command: str
    matches: Matcher
    future: asyncio.Future[Frame]


def _reply(name: str, zone: int, value: str | None = None) -> Matcher:
    wanted = (f"Z{zone}",) if value is None else (f"Z{zone}", value)
    return lambda frame: frame.name == name and frame.args[: len(wanted)] == wanted


def _is_status_start(frame: Frame) -> bool:
    return frame.name in ("PON", "POF")


def _is_ctl_echo(frame: Frame) -> bool:
    return frame.name == "CTL"


class ZonedClient:
    """Talk to one McIntosh unit that speaks the zoned dialect."""

    def __init__(self, transport: Transport, timing: Timing | None = None) -> None:
        self._transport = transport
        self._timing = timing or Timing()
        self._state = zoned.DeviceState()
        self._listeners: list[Listener] = []
        self._connection_listeners: list[ConnectionListener] = []
        self._connected = False
        self._lock = asyncio.Lock()
        self._pending: _Pending | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._last_rx = monotonic()
        self._rx = asyncio.Event()

    # ------------------------------------------------------------ lifecycle
    @property
    def state(self) -> zoned.DeviceState:
        """The last state the unit reported."""
        return self._state

    @property
    def connected(self) -> bool:
        """True from a successful start() until the transport closes or stop()."""
        return self._connected

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Call ``listener`` with the new state whenever it changes."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def add_connection_listener(
        self, listener: ConnectionListener
    ) -> Callable[[], None]:
        """Call ``listener(False)`` when the link drops, ``listener(True)`` on start."""
        self._connection_listeners.append(listener)
        return lambda: self._connection_listeners.remove(listener)

    def _set_connected(self, *, connected: bool) -> None:
        if connected != self._connected:
            self._connected = connected
            for listener in tuple(self._connection_listeners):
                listener(connected)

    async def start(self) -> None:
        """Begin reading, make sure RS232 control is enabled, then load full state."""
        self._read_task = asyncio.get_running_loop().create_task(self._read_loop())
        try:
            await self.query()
        except McIntoshCommandError, McIntoshTimeoutError:
            await self._exchange(
                zoned.enable_rs232(), _is_ctl_echo, self._timing.command
            )
            await self.query()
        self._set_connected(connected=True)

    async def stop(self) -> None:
        """Stop reading and close the transport."""
        task, self._read_task = self._read_task, None
        self._connected = False
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._transport.close()

    # ------------------------------------------------------------- commands
    async def query(self) -> zoned.DeviceState:
        """Request full status; retry once if rejected just after power-up."""
        try:
            await self._exchange(zoned.query(), _is_status_start, self._timing.query)
        except McIntoshCommandError as err:
            if err.code != "1":
                raise
            await asyncio.sleep(self._timing.retry_delay)
            await self._exchange(zoned.query(), _is_status_start, self._timing.query)
        return self._state

    async def set_power(self, zone: int, *, on: bool) -> None:
        """Turn a zone on or off and wait for the unit to confirm."""
        await self._exchange(
            zoned.power(zone, on=on),
            _reply("PON" if on else "POF", zone),
            self._timing.power,
        )

    async def set_volume(self, zone: int, level: int) -> None:
        """Set a zone's volume to the unit's own step number."""
        await self._exchange(
            zoned.volume_set(zone, level),
            _reply("VST", zone, str(level)),
            self._timing.command,
        )

    async def volume_step(self, zone: int, *, up: bool) -> None:
        """Raise or lower a zone's volume by one step."""
        await self._exchange(
            zoned.volume_step(zone, up=up), _reply("VST", zone), self._timing.command
        )

    async def set_mute(self, zone: int, *, muted: bool) -> None:
        """Mute or unmute a zone."""
        await self._exchange(
            zoned.mute(zone, muted=muted),
            _reply("MUT", zone, str(int(muted))),
            self._timing.command,
        )

    async def select_input(self, zone: int, number: int) -> None:
        """Select an input for a zone."""
        await self._exchange(
            zoned.select_input(zone, number),
            _reply("INP", zone, str(number)),
            self._timing.power,
        )

    # -------------------------------------------------------------- plumbing
    async def _exchange(self, command: str, matches: Matcher, wait: float) -> Frame:
        async with self._lock:
            future: asyncio.Future[Frame] = asyncio.get_running_loop().create_future()
            self._pending = _Pending(command, matches, future)
            try:
                await self._transport.write(command.encode("ascii"))
                frame = await asyncio.wait_for(future, wait)
            except TimeoutError as err:
                raise McIntoshTimeoutError(command) from err
            except OSError as err:
                raise McIntoshConnectionError(str(err)) from err
            finally:
                self._pending = None
            await self._settle()
            return frame

    async def _settle(self) -> None:
        """Wait until the unit has been quiet for ``settle`` seconds."""
        deadline = monotonic() + self._timing.settle_max
        with contextlib.suppress(TimeoutError):
            while True:
                quiet_for = self._timing.settle - (monotonic() - self._last_rx)
                remaining = deadline - monotonic()
                if quiet_for <= 0 or remaining <= 0:
                    return
                self._rx.clear()
                await asyncio.wait_for(self._rx.wait(), min(quiet_for, remaining))

    async def _read_loop(self) -> None:
        buffer = ""
        while data := await self._transport.read():
            self._last_rx = monotonic()
            self._rx.set()
            frames, buffer = parse_frames(
                buffer + data.decode("ascii", errors="ignore")
            )
            for frame in frames:
                self._handle(frame)
        _LOGGER.debug("transport closed")
        pending = self._pending
        if pending is not None and not pending.future.done():
            pending.future.set_exception(McIntoshConnectionError("connection closed"))
        self._set_connected(connected=False)

    def _handle(self, frame: Frame) -> None:
        pending = self._pending
        if zoned.is_error(frame):
            code = frame.args[0] if frame.args else "?"
            if pending is not None and not pending.future.done():
                pending.future.set_exception(
                    McIntoshCommandError(code, pending.command)
                )
            return
        before = self._state
        self._state = zoned.apply_frame(before, frame)
        if pending is not None and not pending.future.done() and pending.matches(frame):
            pending.future.set_result(frame)
        if self._state != before:
            for listener in tuple(self._listeners):
                listener(self._state)
