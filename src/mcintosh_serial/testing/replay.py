"""Play a recorded capture back as a unit, so a real session becomes a regression test."""

import asyncio
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from mcintosh_serial.capture import Event


class ReplayMismatchError(AssertionError):
    """The library sent something the capture does not contain at this point."""


class ReplayTransport:
    """A transport that answers exactly as the unit did in a capture.

    Every ``tx`` event expects the library to send those bytes next, and the ``rx`` events
    that follow it are delivered in response. Anything the unit sent before the first ``tx``
    (a banner, for example) is available immediately. A command that is not next in the
    capture raises ``ReplayMismatchError`` naming what was expected, so a changed handshake
    shows up as a clear test failure.
    """

    def __init__(self, events: tuple[Event, ...]) -> None:
        self._steps: list[tuple[str, tuple[str, ...]]] = []
        self._out: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffered = ""
        sent: str | None = None
        replies: list[str] = []
        for event in events:
            if event.direction == "tx":
                self._close_step(sent, replies)
                sent, replies = event.data, []
            else:
                replies.append(event.data)
        self._close_step(sent, replies)

    def _close_step(self, sent: str | None, replies: list[str]) -> None:
        if sent is not None:
            self._steps.append((sent, tuple(replies)))
        else:
            for chunk in replies:  # unsolicited, before anything was sent
                self._out.put_nowait(chunk.encode("latin-1"))

    @property
    def finished(self) -> bool:
        """True once every recorded command has been sent."""
        return not self._steps

    async def read(self) -> bytes:
        """Return the next bytes the recorded unit sent; ``b""`` after close."""
        return await self._out.get()

    async def write(self, data: bytes) -> None:
        """Accept the next command and release the recorded replies."""
        self._buffered += data.decode("latin-1")
        while self._steps and self._buffered.startswith(self._steps[0][0]):
            sent, replies = self._steps.pop(0)
            self._buffered = self._buffered[len(sent) :]
            for chunk in replies:
                await self._out.put(chunk.encode("latin-1"))
        if (
            self._buffered
            and self._steps
            and not self._steps[0][0].startswith(self._buffered)
        ):
            message = (
                f"sent {self._buffered!r} but the capture expects {self._steps[0][0]!r}"
            )
            raise ReplayMismatchError(message)
        if self._buffered and not self._steps:
            message = f"sent {self._buffered!r} after the capture ended"
            raise ReplayMismatchError(message)

    @override
    def __repr__(self) -> str:
        return f"ReplayTransport({len(self._steps)} steps left)"

    async def close(self) -> None:
        """Signal EOF."""
        await self._out.put(b"")
