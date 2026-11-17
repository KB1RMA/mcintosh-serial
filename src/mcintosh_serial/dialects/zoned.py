"""The "zoned" dialect: ``(PON Z1)``, ``(VST Z1 8)``, ``(INP Z1 3)``, ``(CTL 1)``.

Verified on a McIntosh MX119 (9600 8N1, DB9). Also described, for newer
equipment, in McIntosh's RS-232 application note (115200 baud, 3.5 mm jack).
See docs/protocols/zoned.md for the observed behavior.
"""

from dataclasses import replace
import re
from types import MappingProxyType

from mcintosh_serial.dialects.base import Command, Link, Matcher
from mcintosh_serial.errors import McIntoshCommandError, McIntoshTimeoutError
from mcintosh_serial.frames import Frame, parse_frames
from mcintosh_serial.state import DeviceInfo, DeviceState, ZoneState

__all__ = [
    "DeviceInfo",
    "DeviceState",
    "ZoneState",
    "ZonedDialect",
    "apply_frame",
    "apply_frames",
    "enable_rs232",
    "is_error",
    "mute",
    "power",
    "query",
    "select_input",
    "volume_set",
    "volume_step",
]

_ZONE_RE = re.compile(r"^Z(\d)$")


# --------------------------------------------------------------- commands
def enable_rs232(*, on: bool = True) -> str:
    """Build the command that enables or disables RS232 control."""
    return f"(CTL {int(on)})"


def query() -> str:
    """Build the full-status query."""
    return "(QRY)"


def power(zone: int, *, on: bool) -> str:
    """Build a zone power command."""
    return f"({'PON' if on else 'POF'} Z{zone})"


def volume_step(zone: int, *, up: bool) -> str:
    """Build a one-step volume command."""
    return f"({'VUP' if up else 'VDN'} Z{zone})"


def volume_set(zone: int, level: int) -> str:
    """Build an absolute volume command."""
    return f"(VST Z{zone} {level})"


def mute(zone: int, *, muted: bool) -> str:
    """Build a mute command."""
    return f"(MUT Z{zone} {int(muted)})"


def select_input(zone: int, number: int) -> str:
    """Build an input selection command."""
    return f"(INP Z{zone} {number})"


# ------------------------------------------------------------ state updates
def _zone_of(frame: Frame) -> int | None:
    match = _ZONE_RE.match(frame.args[0]) if frame.args else None
    return int(match.group(1)) if match else None


def _update_zone(state: DeviceState, zone: int, **changes: object) -> DeviceState:
    updated = replace(state.zone(zone), **changes)
    return replace(state, zones=MappingProxyType({**state.zones, zone: updated}))


def apply_frame(state: DeviceState, frame: Frame) -> DeviceState:
    """Return the state after one frame; unknown or malformed frames change nothing."""
    zone = _zone_of(frame)
    rest = frame.args[1:]
    if frame.name == "TNQ":  # tuner display, e.g. "(TNQ     87.50 FM  )"
        return replace(state, tuner=" ".join(frame.args))
    if zone is None:
        return state
    if frame.name in ("PON", "POF"):
        return _update_zone(state, zone, power=frame.name == "PON")
    if frame.name in ("INP", "VST") and rest and rest[0].isdigit():
        key = "input" if frame.name == "INP" else "volume"
        return _update_zone(state, zone, **{key: int(rest[0])})
    if frame.name == "MUT" and rest in (("0",), ("1",)):
        return _update_zone(state, zone, muted=rest[0] == "1")
    return state


def apply_frames(state: DeviceState, frames: tuple[Frame, ...]) -> DeviceState:
    """Return the state after applying every frame in order."""
    result = state
    for frame in frames:
        result = apply_frame(result, frame)
    return result


def is_error(frame: Frame) -> bool:
    """Report whether the frame is ``(ERR n)``: 1 unknown command, 3 bad parameter."""
    return frame.name == "ERR"


# ----------------------------------------------------------------- dialect
def _reply(name: str, zone: int, value: str | None = None) -> Matcher:
    wanted = (f"Z{zone}",) if value is None else (f"Z{zone}", value)
    return lambda frame: frame.name == name and frame.args[: len(wanted)] == wanted


_STATUS_NAMES = frozenset({"PON", "POF", "VST", "INP", "MUT"})


def _is_status_start(frame: Frame) -> bool:
    """Complete ``(QRY)`` on its first zone status line.

    The MX119 starts its reply with ``(PON Z1)`` or ``(POF Z1)``. Other units in this style
    (the C2500 among them) are not confirmed to, so any zone status line counts; the settle
    wait that follows collects the rest of the dump.
    """
    return frame.name in _STATUS_NAMES and _zone_of(frame) is not None


def _is_ctl_echo(frame: Frame) -> bool:
    return frame.name == "CTL"


class ZonedDialect:
    """The MX119's command style."""

    name = "zoned"
    # (ERR 1) to a query right after power-up is transient.
    retry_query_codes = frozenset({"1"})

    def feed(self, buffer: str, text: str) -> tuple[tuple[Frame, ...], str]:
        """Cut the stream into ``(...)`` frames."""
        return parse_frames(buffer + text)

    def apply(self, state: DeviceState, frame: Frame) -> DeviceState:
        """Return the state after one frame."""
        return apply_frame(state, frame)

    def error_code(self, frame: Frame) -> str | None:
        """Return the code of an ``(ERR n)`` frame."""
        if not is_error(frame):
            return None
        return frame.args[0] if frame.args else "?"

    def query_commands(self) -> tuple[Command, ...]:
        """One ``(QRY)`` loads everything."""
        return (Command(query(), _is_status_start, "query"),)

    def probe(self) -> Command:
        """``(CTL 1)`` enables RS232 control, which the unit needs before it answers anything."""
        return Command(enable_rs232(), _is_ctl_echo)

    async def handshake(self, link: Link) -> None:
        """Query; if the unit refuses, enable RS232 control and query again."""
        try:
            await link.query()
        except McIntoshCommandError, McIntoshTimeoutError:
            await link.exchange(Command(enable_rs232(), _is_ctl_echo))
            await link.query()

    def power(self, zone: int, *, on: bool) -> Command:
        """Turn a zone on or off."""
        return Command(
            power(zone, on=on), _reply("PON" if on else "POF", zone), "power"
        )

    async def after_power(self, link: Link, zone: int, *, on: bool) -> None:
        """Nothing to do: the MX119 needs no setup after power changes."""

    def volume_set(self, zone: int, level: int) -> Command:
        """Set a zone's volume."""
        return Command(
            volume_set(zone, level), _reply("VST", zone, str(level)), "volume"
        )

    def volume_step(self, zone: int, *, up: bool) -> Command:
        """Raise or lower a zone's volume by one step."""
        return Command(volume_step(zone, up=up), _reply("VST", zone))

    def mute(self, zone: int, *, muted: bool) -> Command:
        """Mute or unmute a zone."""
        return Command(mute(zone, muted=muted), _reply("MUT", zone, str(int(muted))))

    def select_input(self, zone: int, number: int) -> Command:
        """Select an input for a zone."""
        return Command(
            select_input(zone, number), _reply("INP", zone, str(number)), "power"
        )
