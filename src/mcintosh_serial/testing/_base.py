"""Shared plumbing for the in-process unit emulators."""

from abc import ABC, abstractmethod
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Coroutine


class FakeUnit(ABC):
    """A fake unit that implements the client's transport interface.

    Subclasses say how to cut the byte stream into commands (``_split``) and how to
    answer one (``_dispatch``). ``time_scale`` multiplies every delay the real unit
    shows, so tests stay fast.
    """

    drops_when_busy = (
        True  # the MX119 ignores commands that arrive while it is replying
    )

    def __init__(self, time_scale: float = 0.01) -> None:
        self.time_scale = time_scale
        self.dropped: list[str] = []
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self._in = ""
        self._busy = False
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    # ---------------------------------------------------------------- wire
    async def read(self) -> bytes:
        """Return the next bytes the unit sends; ``b""`` after close."""
        return await self._out.get()

    async def write(self, data: bytes) -> None:
        """Accept bytes from the client and run each complete command."""
        commands, self._in = self._split(
            self._in + data.decode("ascii", errors="ignore")
        )
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

    # ------------------------------------------------------------- helpers
    @abstractmethod
    def _split(self, text: str) -> tuple[list[str], str]:
        """Cut received text into complete commands; return them and the unfinished rest."""

    @abstractmethod
    async def _dispatch(self, command: str) -> None:
        """Answer one command."""

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds * self.time_scale)

    async def _emit_raw(self, text: str) -> None:
        await self._out.put(text.encode("ascii"))

    async def _handle(self, command: str) -> None:
        if not self.drops_when_busy:
            async with (
                self._lock
            ):  # a unit with no rate limit works through commands in order
                await self._dispatch(command)
            return
        if self._busy:
            self.dropped.append(command)
            return
        self._busy = True
        try:
            await self._dispatch(command)
        finally:
            self._busy = False
