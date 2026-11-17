"""What a command style (dialect) has to provide.

A dialect is a small, mostly pure module: how to cut the byte stream into frames,
how a frame changes the known state, and how to build each command together with
the reply that completes it. The generic client does the rest (pacing, timeouts,
listeners), so supporting a unit that speaks a known dialect needs no new code,
only a model profile.
"""

from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from mcintosh_serial.frames import Frame

if TYPE_CHECKING:
    from mcintosh_serial.state import DeviceState

Matcher = Callable[[Frame], bool]
Wait = Literal["command", "query", "power", "volume", "optional"]


@dataclass(frozen=True, slots=True)
class Command:
    """One thing to send and the reply that completes it."""

    payload: str  # exact text to send, terminator included
    matches: Matcher  # the reply frame that completes the command
    wait: Wait = "command"  # which Timing value bounds the wait
    _: KW_ONLY
    skip_if: Callable[[DeviceState], bool] | None = None  # already done: send nothing
    # False: a missing or rejected reply is tolerated (optional queries).
    required: bool = True


class Link(Protocol):
    """What a dialect's handshake may use."""

    @property
    def state(self) -> DeviceState:
        """The state reported so far."""
        ...

    async def exchange(self, command: Command) -> Frame:
        """Send a command and wait for its reply."""
        ...

    async def query(self) -> DeviceState:
        """Load the unit's full state."""
        ...


class Dialect(Protocol):
    """A command style."""

    name: str
    # Error codes for which a failed query is retried once (for example just after power-up).
    retry_query_codes: frozenset[str]

    def feed(self, buffer: str, text: str) -> tuple[tuple[Frame, ...], str]:
        """Add received text to the buffer; return complete frames and the remainder."""
        ...

    def apply(self, state: DeviceState, frame: Frame) -> DeviceState:
        """Return the state after one frame."""
        ...

    def error_code(self, frame: Frame) -> str | None:
        """Return the error code if the frame is an error reply, else None."""
        ...

    def query_commands(self) -> tuple[Command, ...]:
        """Commands that together load the full state."""
        ...

    def probe(self) -> Command:
        """Return a harmless command any unit of this dialect answers, for detection."""
        ...

    async def handshake(self, link: Link) -> None:
        """Get the unit ready for control and load its state."""
        ...

    def power(self, zone: int, *, on: bool) -> Command:
        """Turn a zone on or off."""
        ...

    async def after_power(self, link: Link, zone: int, *, on: bool) -> None:
        """Run once a power command is confirmed (for setup the unit refuses in standby)."""
        ...

    def volume_set(self, zone: int, level: int) -> Command:
        """Set a zone's volume."""
        ...

    def volume_step(self, zone: int, *, up: bool) -> Command:
        """Raise or lower a zone's volume by one step."""
        ...

    def mute(self, zone: int, *, muted: bool) -> Command:
        """Mute or unmute a zone."""
        ...

    def select_input(self, zone: int, number: int) -> Command:
        """Select an input for a zone."""
        ...
