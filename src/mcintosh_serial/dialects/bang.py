"""The "bang" dialect: ``!POWER?``, ``!VOL(25)``, ``!SRC(3)``, replies like ``!VOL(25)``.

Used by the MX160, MX170 and MX180 processors: commands start with ``!`` and end with a
carriage return, parameters sit in parentheses, and the unit answers one line per command.
Built from the command names and reply formats of the hass-mcintosh project (which marks
the MX160 as tested and the others as untested). How the unit answers *set* commands and
errors is not documented anywhere we found, so set commands accept any reply line, and
zone 2 power is not supported until its reply is known. Not yet confirmed on hardware with
this library. See docs/protocols/bang.md.
"""

import contextlib
from dataclasses import replace
import re
from types import MappingProxyType
from typing import TYPE_CHECKING

from mcintosh_serial.dialects.base import Command, Link, Matcher
from mcintosh_serial.errors import McIntoshCommandError, McIntoshTimeoutError
from mcintosh_serial.frames import Frame

if TYPE_CHECKING:
    from mcintosh_serial.state import DeviceState

_LINE = re.compile(r"^!([A-Za-z0-9+-]+)(?:\(([^)]*)\))?\s*(.*)$")
_TERMINATOR = "\r"
_MAIN, _SECOND = 1, 2
# frame name -> (zone, ZoneState field)
_FIELDS = {
    "POWER": (_MAIN, "power"),
    "VOL": (_MAIN, "volume"),
    "MUTE": (_MAIN, "muted"),
    "SRC": (_MAIN, "input"),
    "ZVOL": (_SECOND, "volume"),
    "ZMUTE": (_SECOND, "muted"),
    "ZSRC": (_SECOND, "input"),
}
_BOOLEAN_FIELDS = frozenset({"power", "muted"})
_VERBOSITY = 2


def _command(text: str) -> str:
    return f"{text}{_TERMINATOR}"


def _reply(name: str) -> Matcher:
    return lambda frame: frame.name == name


# Names of the replies to the library's queries.
_QUERY_REPLIES = frozenset({*_FIELDS, "DEVICE", "PONG"})


def _set_reply(*names: str) -> Matcher:
    """Match a set command's reply, whose format is unconfirmed.

    Accept the line naming the command's own value, or any line we do not know, but not a
    reply to some other query that arrived late.
    """
    return lambda frame: frame.name in names or frame.name not in _QUERY_REPLIES


def _parse_line(line: str) -> Frame | None:
    match = _LINE.match(line.strip())
    if match is None:
        return None
    name, value, rest = match.groups()
    args = tuple(part for part in (value, rest.strip().strip('"')) if part)
    return Frame(name.upper(), args, line.strip())


def _check_zone(zone: int) -> None:
    if zone not in (_MAIN, _SECOND):
        message = f"this dialect has zones 1 and 2, got zone {zone}"
        raise ValueError(message)


def _names(zone: int, main: str, second: str) -> str:
    _check_zone(zone)
    return main if zone == _MAIN else second


class BangDialect:
    """The MX160 family's command style."""

    name = "bang"
    retry_query_codes: frozenset[str] = frozenset()

    def feed(self, buffer: str, text: str) -> tuple[tuple[Frame, ...], str]:
        """Cut the stream into lines; keep an unfinished last line for the next chunk."""
        *lines, rest = re.split(r"[\r\n]+", buffer + text)
        frames = tuple(
            frame for line in lines if (frame := _parse_line(line)) is not None
        )
        return frames, rest

    def apply(self, state: DeviceState, frame: Frame) -> DeviceState:
        """Return the state after one reply line; unknown lines change nothing."""
        if frame.name == "DEVICE" and frame.args:
            return replace(state, info=replace(state.info, model=frame.args[0]))
        target = _FIELDS.get(frame.name)
        if target is None or not frame.args:
            return state
        zone, field = target
        value = frame.args[0]
        if not value.isdigit():
            return state
        parsed: bool | int = value == "1" if field in _BOOLEAN_FIELDS else int(value)
        updated = replace(state.zone(zone), **{field: parsed})
        return replace(state, zones=MappingProxyType({**state.zones, zone: updated}))

    def error_code(self, frame: Frame) -> str | None:
        """Return the code of an ``!ERR...`` line (assumed format), else None."""
        if not frame.name.startswith("ERR"):
            return None
        return frame.args[0] if frame.args else frame.name

    def query_commands(self) -> tuple[Command, ...]:
        """Ask for each value in turn; only the power query is required."""
        return (
            Command(_command("!DEVICE?"), _reply("DEVICE"), "optional", required=False),
            Command(_command("!POWER?"), _reply("POWER"), "query"),
            Command(_command("!VOL?"), _reply("VOL"), "optional", required=False),
            Command(_command("!MUTE?"), _reply("MUTE"), "optional", required=False),
            Command(_command("!SRC?"), _reply("SRC"), "optional", required=False),
            Command(_command("!ZVOL?"), _reply("ZVOL"), "optional", required=False),
            Command(_command("!ZMUTE?"), _reply("ZMUTE"), "optional", required=False),
            Command(_command("!ZSRC?"), _reply("ZSRC"), "optional", required=False),
        )

    def probe(self) -> Command:
        """``!PING?`` is harmless and answers ``!PONG``."""
        return Command(_command("!PING?"), _reply("PONG"), "query")

    async def handshake(self, link: Link) -> None:
        """Set the verbosity the other projects use, then load state."""
        with contextlib.suppress(McIntoshCommandError, McIntoshTimeoutError):
            await link.exchange(Command(_command(f"!VERB({_VERBOSITY})"), _set_reply()))
            # a unit that does not take this still answers the queries
        await link.query()

    def power(self, zone: int, *, on: bool) -> Command:
        """Turn the main zone on or off. Zone 2 power is not supported yet."""
        if zone != _MAIN:
            message = "zone 2 power is not supported: its reply format is not known"
            raise ValueError(message)
        return Command(
            _command("!PON" if on else "!POFF"), _set_reply("POWER"), "power"
        )

    async def after_power(self, link: Link, zone: int, *, on: bool) -> None:
        """Nothing to do: no setup is known to be needed after power changes."""

    def volume_set(self, zone: int, level: int) -> Command:
        """Set a zone's volume."""
        name = _names(zone, "VOL", "ZVOL")
        return Command(_command(f"!{name}({level})"), _set_reply(name), "volume")

    def volume_step(self, zone: int, *, up: bool) -> Command:
        """Raise or lower a zone's volume by one step."""
        name = _names(zone, "VOL", "ZVOL")
        return Command(_command(f"!{name}{'+' if up else '-'}"), _set_reply(name))

    def mute(self, zone: int, *, muted: bool) -> Command:
        """Mute or unmute a zone."""
        base = _names(zone, "MUTE", "ZMUTE")
        return Command(_command(f"!{base}{'ON' if muted else 'OFF'}"), _set_reply(base))

    def select_input(self, zone: int, number: int) -> Command:
        """Select an input for a zone."""
        name = _names(zone, "SRC", "ZSRC")
        return Command(_command(f"!{name}({number})"), _set_reply(name))
