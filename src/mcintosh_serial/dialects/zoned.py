"""The "zoned" dialect: ``(PON Z1)``, ``(VST Z1 8)``, ``(INP Z1 3)``, ``(CTL 1)``.

Verified on a McIntosh MX119 (9600 8N1, DB9). Also described, for newer
equipment, in McIntosh's RS-232 application note (115200 baud, 3.5 mm jack).
See docs/protocols/zoned.md for the observed behavior.
"""

from dataclasses import dataclass, field, replace
import re
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mcintosh_serial.frames import Frame

_ZONE_RE = re.compile(r"^Z(\d)$")


@dataclass(frozen=True, slots=True)
class ZoneState:
    """Known state of one zone; None means not yet reported."""

    power: bool | None = None
    input: int | None = None
    volume: int | None = None
    muted: bool | None = None


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Immutable snapshot of everything the unit has reported."""

    zones: Mapping[int, ZoneState] = field(default_factory=lambda: MappingProxyType({}))
    tuner: str | None = None

    def zone(self, number: int) -> ZoneState:
        """Return one zone's state (all None if the unit has not reported it)."""
        return self.zones.get(number, ZoneState())


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
