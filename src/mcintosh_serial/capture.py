"""Record what passes between the library and a unit, so a real session can be shared and replayed.

A capture is a list of ``Event`` objects, stored one JSON object per line. The ``capture``
command writes them; ``mcintosh_serial.testing.ReplayTransport`` plays them back in tests,
so a contributor's capture becomes a regression test for their model.
"""

from dataclasses import dataclass
import json
import re
from time import monotonic
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mcintosh_serial.transport import Transport

Direction = Literal["tx", "rx"]
_SERIAL_NUMBER = re.compile(r"(Serial Number:\s*)[^\s)]+")


@dataclass(frozen=True, slots=True)
class Event:
    """One chunk of bytes sent to (tx) or received from (rx) the unit."""

    direction: Direction
    data: str  # latin-1 text, so every byte value survives a round trip
    t: float = 0.0  # seconds since the capture started; 0 when not recorded


def events_to_jsonl(events: tuple[Event, ...]) -> str:
    """Serialize events, one JSON object per line."""
    return "".join(
        json.dumps({"t": round(e.t, 3), "dir": e.direction, "data": e.data}) + "\n"
        for e in events
    )


def events_from_jsonl(text: str) -> tuple[Event, ...]:
    """Parse events written by ``events_to_jsonl``; ``t`` is optional."""
    rows = (json.loads(line) for line in text.splitlines() if line.strip())
    return tuple(
        Event(row["dir"], row["data"], float(row.get("t", 0.0))) for row in rows
    )


def redact(text: str) -> str:
    """Hide the unit's serial number so a capture can be posted publicly."""
    return _SERIAL_NUMBER.sub(r"\1<redacted>", text)


class RecordingTransport:
    """Wrap a transport and note every byte that passes through it."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner
        self._start = monotonic()
        self.events: list[Event] = []

    def _note(self, direction: Direction, data: bytes) -> None:
        self.events.append(
            Event(direction, data.decode("latin-1"), monotonic() - self._start)
        )

    async def read(self) -> bytes:
        """Read from the unit, recording what arrives."""
        data = await self._inner.read()
        if data:
            self._note("rx", data)
        return data

    async def write(self, data: bytes) -> None:
        """Write to the unit, recording what is sent."""
        self._note("tx", data)
        await self._inner.write(data)

    async def close(self) -> None:
        """Close the wrapped transport."""
        await self._inner.close()


@dataclass(frozen=True, slots=True)
class Report:
    """Everything the issue text needs."""

    version: str
    model: str
    dialect: str
    baudrate: int
    link: str
    outcome: str
    events: tuple[Event, ...]

    def render(self, *, redact_serial: bool = True) -> str:
        """Build the Markdown that goes into a "new device" issue."""
        lines = [
            f"{e.t:7.3f} {e.direction.upper()}  {(redact(e.data) if redact_serial else e.data)!r}"
            for e in self.events
        ]
        transcript = "\n".join(lines) or "(nothing was sent or received)"
        return (
            "## McIntosh capture\n\n"
            f"- mcintosh-serial: {self.version}\n"
            f"- Model: {self.model}\n"
            f"- Command style tried: {self.dialect}\n"
            f"- Baud rate: {self.baudrate}\n"
            f"- Link: {self.link}\n\n"
            f"### Result\n\n{self.outcome}\n\n"
            f"### Transcript\n\n```text\n{transcript}\n```\n"
        )
