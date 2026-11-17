"""Find out which command style a unit speaks, using only harmless commands."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from mcintosh_serial.client import Client, Timing
from mcintosh_serial.dialects import DIALECTS, get_dialect
from mcintosh_serial.errors import McIntoshCommandError, McIntoshError
from mcintosh_serial.transport import Transport

COMMON_BAUDRATES = (9600, 115200, 19200, 38400, 57600)
_PROBE_TIMING = Timing(command=1.0, query=1.5, settle=0.2, settle_max=1.0)

OpenAt = Callable[[int], Awaitable[Transport]]


@dataclass(frozen=True, slots=True)
class Detection:
    """A dialect that answered at a baud rate."""

    dialect: str
    baudrate: int
    reply: str  # what the unit said, for the report


async def _probe(open_at: OpenAt, baudrate: int, dialect_name: str) -> Detection | None:
    transport = await open_at(baudrate)
    dialect = get_dialect(dialect_name)
    client = Client(transport, dialect, _PROBE_TIMING)
    client.begin()
    try:
        frame = await client.exchange(dialect.probe())
        return Detection(dialect_name, baudrate, frame.raw)
    except McIntoshCommandError as err:
        return Detection(
            dialect_name, baudrate, f"error reply: {err.code}"
        )  # it answered
    except McIntoshError:
        return None
    finally:
        await client.stop()


async def detect(
    open_at: OpenAt,
    baudrates: Iterable[int] = COMMON_BAUDRATES,
    dialects: Iterable[str] | None = None,
) -> list[Detection]:
    """Try each dialect's harmless probe at each baud rate; return the ones that answered."""
    names = tuple(dialects) if dialects is not None else tuple(sorted(DIALECTS))
    hits = [
        await _probe(open_at, baudrate, name)
        for baudrate in baudrates
        for name in names
    ]
    return [hit for hit in hits if hit is not None]
