"""Async client, generic over the command style (dialect).

One command is in flight at a time. After the expected reply arrives the client
waits for the line to go quiet before releasing the next command, because the
units drop commands that arrive while they are still sending a reply.
"""

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING

from mcintosh_serial.dialects import get_dialect
from mcintosh_serial.dialects.zoned import ZonedDialect
from mcintosh_serial.errors import (
    McIntoshCommandError,
    McIntoshConnectionError,
    McIntoshTimeoutError,
)
from mcintosh_serial.state import DeviceState

if TYPE_CHECKING:
    from mcintosh_serial.dialects.base import Command, Dialect, Wait
    from mcintosh_serial.frames import Frame
    from mcintosh_serial.profiles import Profile
    from mcintosh_serial.transport import Transport

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[DeviceState], None]
ConnectionListener = Callable[[bool], None]


@dataclass(frozen=True, slots=True)
class Timing:
    """Seconds. Defaults come from the MX119; override per model or in tests."""

    command: float = 2.0
    query: float = 4.0
    power: float = 12.0
    volume: float = 2.0  # a volume set; longer for units that ramp to the target
    optional: float = 1.0  # an optional query, which some units never answer
    settle: float = 0.3  # quiet time after a reply before the next command
    settle_max: float = 3.0
    retry_delay: float = 1.0  # wait before retrying a query rejected after power-up


@dataclass(slots=True)
class _Pending:
    command: Command
    future: asyncio.Future[Frame]


class Client:
    """Talk to one McIntosh unit using the given dialect."""

    def __init__(
        self,
        transport: Transport,
        dialect: Dialect,
        timing: Timing | None = None,
    ) -> None:
        self._transport = transport
        self._dialect = dialect
        self._timing = timing or Timing()
        self._state = DeviceState()
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
    def dialect(self) -> Dialect:
        """The command style this client speaks."""
        return self._dialect

    @property
    def state(self) -> DeviceState:
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

    def begin(self) -> None:
        """Start reading from the transport without sending anything."""
        if self._read_task is None:
            self._read_task = asyncio.get_running_loop().create_task(self._read_loop())

    async def start(self) -> None:
        """Begin reading, get the unit ready for control, and load its full state."""
        self.begin()
        await self._dialect.handshake(self)
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
    async def query(self) -> DeviceState:
        """Request full status; retry once if rejected just after power-up."""
        try:
            await self._run_query()
        except McIntoshCommandError as err:
            if err.code not in self._dialect.retry_query_codes:
                raise
            await asyncio.sleep(self._timing.retry_delay)
            await self._run_query()
        return self._state

    async def _run_query(self) -> None:
        for command in self._dialect.query_commands():
            try:
                await self.exchange(command)
            except McIntoshCommandError, McIntoshTimeoutError:
                if command.required:
                    raise

    async def set_power(self, zone: int, *, on: bool) -> None:
        """Turn a zone on or off and wait for the unit to confirm."""
        await self._send(self._dialect.power(zone, on=on))
        await self._dialect.after_power(self, zone, on=on)

    async def set_volume(self, zone: int, level: int) -> None:
        """Set a zone's volume to the unit's own step number."""
        await self._send(self._dialect.volume_set(zone, level))

    async def volume_step(self, zone: int, *, up: bool) -> None:
        """Raise or lower a zone's volume by one step."""
        await self._send(self._dialect.volume_step(zone, up=up))

    async def set_mute(self, zone: int, *, muted: bool) -> None:
        """Mute or unmute a zone."""
        await self._send(self._dialect.mute(zone, muted=muted))

    async def select_input(self, zone: int, number: int) -> None:
        """Select an input for a zone."""
        await self._send(self._dialect.select_input(zone, number))

    async def _send(self, command: Command) -> None:
        if command.skip_if is not None and command.skip_if(self._state):
            return  # the unit does not acknowledge a change to the value it already has
        await self.exchange(command)

    # -------------------------------------------------------------- plumbing
    def _wait_for(self, wait: Wait) -> float:
        return {
            "command": self._timing.command,
            "query": self._timing.query,
            "power": self._timing.power,
            "volume": self._timing.volume,
            "optional": self._timing.optional,
        }[wait]

    async def exchange(self, command: Command) -> Frame:
        """Send one command and wait for its reply, then for the line to go quiet."""
        async with self._lock:
            future: asyncio.Future[Frame] = asyncio.get_running_loop().create_future()
            self._pending = _Pending(command, future)
            try:
                await self._transport.write(command.payload.encode("ascii"))
                frame = await asyncio.wait_for(future, self._wait_for(command.wait))
            except TimeoutError as err:
                raise McIntoshTimeoutError(command.payload) from err
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
            frames, buffer = self._dialect.feed(
                buffer, data.decode("ascii", errors="ignore")
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
        code = self._dialect.error_code(frame)
        if code is not None:
            if pending is not None and not pending.future.done():
                pending.future.set_exception(
                    McIntoshCommandError(code, pending.command.payload)
                )
            return
        before = self._state
        self._state = self._dialect.apply(before, frame)
        if (
            pending is not None
            and not pending.future.done()
            and pending.command.matches(frame)
        ):
            pending.future.set_result(frame)
        if self._state != before:
            for listener in tuple(self._listeners):
                listener(self._state)


class ZonedClient(Client):
    """A client for units that speak the zoned dialect (the MX119)."""

    def __init__(self, transport: Transport, timing: Timing | None = None) -> None:
        super().__init__(transport, ZonedDialect(), timing)


def client_for(transport: Transport, profile: Profile) -> Client:
    """Create a client for a model profile (its dialect and timing)."""
    return Client(transport, get_dialect(profile.dialect), profile.timing)
