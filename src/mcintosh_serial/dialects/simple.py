"""The "simple" dialect: ``(PWR 1)``, ``(VOL 65)``, ``(INP 3)``, ``(QRY)``, ``(STA 1)``.

Used by the MA352 and MA5300 integrated amplifiers: one zone, commands without a
zone token, the unit echoes each command as its acknowledgement and pushes status
changes when status reporting is on. Built from McIntosh's MA5300 external control
document and from the behavior reported by the mcintosh-ma352-hass project;
not yet confirmed on hardware with this library. See docs/protocols/simple.md.
"""

import contextlib
from dataclasses import replace
import re
from types import MappingProxyType
from typing import TYPE_CHECKING

from mcintosh_serial.dialects.base import Command, Link, Matcher
from mcintosh_serial.errors import McIntoshCommandError, McIntoshTimeoutError
from mcintosh_serial.frames import Frame, parse_frames

if TYPE_CHECKING:
    from mcintosh_serial.state import DeviceInfo, DeviceState

_MODEL_RE = re.compile(r"^[A-Z]{1,3}\d{2,5}$")
_TERMINATOR = "\r"
_NUMERIC = {"VOL": "volume", "INP": "input"}
_ONE_ZONE = 1


def _command(name: str, parameter: str | int | None = None) -> str:
    body = name if parameter is None else f"{name} {parameter}"
    return f"({body}){_TERMINATOR}"


def _check_zone(zone: int) -> None:
    if zone != _ONE_ZONE:
        message = f"this dialect has one zone, got zone {zone}"
        raise ValueError(message)


def _echo(name: str, value: str | None = None) -> Matcher:
    wanted = () if value is None else (value,)
    return lambda frame: frame.name == name and frame.args[: len(wanted)] == wanted


def _is_model(frame: Frame) -> bool:
    return not frame.args and _MODEL_RE.match(frame.name) is not None


def _is_status_start(frame: Frame) -> bool:
    return frame.name == "PWR" or _is_model(frame)


async def _enable_status_push(link: Link) -> None:
    # A unit already pushing does not acknowledge this; one that refuses it still works,
    # it just will not push changes. Neither should fail startup or power-on.
    with contextlib.suppress(McIntoshCommandError, McIntoshTimeoutError):
        await link.exchange(Command(_command("STA", 1), _echo("STA", "1")))


def _set_zone(state: DeviceState, **changes: object) -> DeviceState:
    zone = replace(state.zone(_ONE_ZONE), **changes)
    return replace(state, zones=MappingProxyType({**state.zones, _ONE_ZONE: zone}))


class SimpleDialect:
    """The MA352 and MA5300's command style."""

    name = "simple"
    retry_query_codes: frozenset[str] = frozenset()

    def feed(self, buffer: str, text: str) -> tuple[tuple[Frame, ...], str]:
        """Cut the stream into ``(...)`` frames."""
        return parse_frames(buffer + text)

    def apply(self, state: DeviceState, frame: Frame) -> DeviceState:
        """Return the state after one frame; unknown frames change nothing."""
        value = frame.args[0] if frame.args else ""
        if frame.name == "PWR" and value in ("0", "1"):
            return _set_zone(state, power=value == "1")
        if frame.name == "MUT" and value in ("0", "1"):
            return _set_zone(state, muted=value == "1")
        if frame.name in _NUMERIC and value.isdigit():
            return _set_zone(state, **{_NUMERIC[frame.name]: int(value)})
        if frame.name == "STA" and value in ("0", "1"):
            return replace(state, status_push=value == "1")
        if _is_model(frame):
            return replace(state, info=replace(state.info, model=frame.name))
        return self._apply_info(state, frame)

    @staticmethod
    def _apply_info(state: DeviceState, frame: Frame) -> DeviceState:
        text = " ".join((frame.name, *frame.args))
        info: DeviceInfo = state.info
        if text.startswith("Serial Number:"):
            return replace(
                state, info=replace(info, serial_number=text.split(":", 1)[1].strip())
            )
        if text.startswith("FW Version:"):
            return replace(
                state, info=replace(info, firmware=text.split(":", 1)[1].strip())
            )
        return state

    def error_code(self, frame: Frame) -> str | None:
        """Return the text of an ``(ERROR - ...)`` frame, e.g. ``Invalid Command``."""
        if frame.name != "ERROR":
            return None
        return " ".join(frame.args).removeprefix("-").strip() or "?"

    def query_commands(self) -> tuple[Command, ...]:
        """One ``(QRY)`` loads everything (only product info while in standby)."""
        return (Command(_command("QRY"), _is_status_start, "query"),)

    def probe(self) -> Command:
        """``(QRY)`` is harmless and answers even in standby."""
        return Command(
            _command("QRY"),
            lambda frame: _is_status_start(frame) or frame.name == "ERROR",
            "query",
        )

    async def handshake(self, link: Link) -> None:
        """Load state, then make sure the unit pushes its changes."""
        await link.query()
        if link.state.status_push is False:
            await _enable_status_push(link)

    async def after_power(self, link: Link, zone: int, *, on: bool) -> None:
        """After power-on, turn status reporting on if it was not seen to be on.

        In standby ``(QRY)`` does not report ``STA`` and the unit refuses ``(STA 1)``, so a
        client started in standby only learns the setting once the amplifier is on.
        """
        _check_zone(zone)
        if on and link.state.status_push is not True:
            await _enable_status_push(link)

    def power(self, zone: int, *, on: bool) -> Command:
        """Turn the amplifier on or off (about 16 s of start-up follow power-on)."""
        _check_zone(zone)
        return Command(_command("PWR", int(on)), _echo("PWR", str(int(on))), "power")

    def volume_set(self, zone: int, level: int) -> Command:
        """Set the volume; the unit ramps in 1 % steps and pushes each, so wait for the target."""
        _check_zone(zone)
        return Command(
            _command("VOL", level),
            _echo("VOL", str(level)),
            "volume",
            skip_if=lambda state: state.zone(_ONE_ZONE).volume == level,
        )

    def volume_step(self, zone: int, *, up: bool) -> Command:
        """Raise or lower the volume one step; the reply carries the new absolute value."""
        _check_zone(zone)
        return Command(_command("VOL", "U" if up else "D"), _echo("VOL"))

    def mute(self, zone: int, *, muted: bool) -> Command:
        """Mute or unmute."""
        _check_zone(zone)
        return Command(_command("MUT", int(muted)), _echo("MUT", str(int(muted))))

    def select_input(self, zone: int, number: int) -> Command:
        """Select an input."""
        _check_zone(zone)
        return Command(_command("INP", number), _echo("INP", str(number)))
