"""The state model shared by every dialect: what a unit has reported so far."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ZoneState:
    """Known state of one zone; None means not yet reported."""

    power: bool | None = None
    input: int | None = None
    volume: int | None = None
    muted: bool | None = None


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Product information, for units that report it."""

    model: str | None = None
    serial_number: str | None = None
    firmware: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Immutable snapshot of everything the unit has reported."""

    zones: Mapping[int, ZoneState] = field(default_factory=lambda: MappingProxyType({}))
    tuner: str | None = None
    # Whether the unit pushes changes by itself; None for dialects with no such switch.
    status_push: bool | None = None
    info: DeviceInfo = field(default_factory=DeviceInfo)

    def zone(self, number: int) -> ZoneState:
        """Return one zone's state (all None if the unit has not reported it)."""
        return self.zones.get(number, ZoneState())
