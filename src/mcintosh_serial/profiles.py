"""Model profiles: everything specific to one McIntosh model, as data.

Each model is one TOML file in ``mcintosh_serial/models``. A model that speaks a
dialect the library already knows needs nothing else, so adding one is a data change.
"""

from dataclasses import dataclass
import functools
from importlib import resources
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from mcintosh_serial.client import Timing
from mcintosh_serial.dialects import DIALECTS

if TYPE_CHECKING:
    from collections.abc import Mapping

# verified: confirmed on real hardware with this library. reported: another project says it
# works on real hardware, not yet confirmed here. untested: built from documents or assumption.
Status = Literal["verified", "reported", "untested"]
_STATUSES: tuple[Status, ...] = ("verified", "reported", "untested")


class ProfileError(ValueError):
    """A model file is missing something or has a value the library cannot use."""


@dataclass(frozen=True, slots=True)
class Profile:
    """Settings for one model."""

    id: str
    name: str
    dialect: str
    status: Status
    baudrate: int
    zones: tuple[int, ...]
    inputs: Mapping[int, str]
    volume_max: int | None
    connector: str
    timing: Timing
    documents: tuple[str, ...]
    references: tuple[str, ...]
    notes: str


def _require[T](data: Mapping[str, Any], key: str, kind: type[T], source: str) -> T:
    value = data.get(key)
    if not isinstance(value, kind):
        message = f"{source}: '{key}' is required and must be a {kind.__name__}"
        raise ProfileError(message)
    return value


def parse_profile(data: Mapping[str, Any], source: str) -> Profile:
    """Validate parsed TOML and build a Profile; ``source`` names the file in errors."""
    profile_id = _require(data, "id", str, source)
    dialect = _require(data, "dialect", str, source)
    if dialect not in DIALECTS:
        message = f"{source}: unknown dialect {dialect!r} (known: {', '.join(sorted(DIALECTS))})"
        raise ProfileError(message)
    status = _require(data, "status", str, source)
    if status not in _STATUSES:
        message = f"{source}: status must be one of {', '.join(_STATUSES)}"
        raise ProfileError(message)
    raw_zones = cast("list[Any]", _require(data, "zones", list, source))
    if not raw_zones or not all(isinstance(z, int) and z > 0 for z in raw_zones):
        message = f"{source}: zones must be a list of positive integers"
        raise ProfileError(message)
    zones = tuple(cast("int", z) for z in raw_zones)
    raw_inputs = cast("dict[Any, Any]", _require(data, "inputs", dict, source))
    try:
        inputs = {int(number): str(name) for number, name in raw_inputs.items()}
    except ValueError:
        message = f"{source}: input numbers must be integers"
        raise ProfileError(message) from None
    references = cast("dict[str, Any]", data.get("references", {}))
    return Profile(
        id=profile_id,
        name=_require(data, "name", str, source),
        dialect=dialect,
        status=status,
        baudrate=_require(data, "baudrate", int, source),
        zones=zones,
        inputs=MappingProxyType(inputs),
        volume_max=cast("int | None", data.get("volume_max")),
        connector=_require(data, "connector", str, source),
        timing=Timing(**cast("dict[str, float]", data.get("timing", {}))),
        documents=tuple(references.get("documents", ())),
        references=tuple(references.get("projects", ())),
        notes=str(data.get("notes", "")),
    )


@functools.cache
def load_profiles() -> Mapping[str, Profile]:
    """Load every model file shipped with the library."""
    found: dict[str, Profile] = {}
    for entry in sorted(
        resources.files("mcintosh_serial").joinpath("models").iterdir(),
        key=lambda item: item.name,
    ):
        if entry.name.endswith(".toml"):
            profile = parse_profile(tomllib.loads(entry.read_text("utf-8")), entry.name)
            if profile.id in found:
                message = f"{entry.name}: duplicate model id {profile.id!r}"
                raise ProfileError(message)
            found[profile.id] = profile
    return MappingProxyType(found)


def get_profile(model: str) -> Profile:
    """Return the profile for a model id such as ``"mx119"``."""
    profiles = load_profiles()
    try:
        return profiles[model.lower()]
    except KeyError:
        message = f"unknown model {model!r} (known: {', '.join(sorted(profiles))})"
        raise ValueError(message) from None
