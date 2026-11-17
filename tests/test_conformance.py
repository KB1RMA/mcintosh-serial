"""Rules every model and command style must follow, checked automatically.

Add a model file and these run against it with no further work: the docs table must list it, it must cite a
source, and its command style's emulator must be able to drive it.
"""

from pathlib import Path
import re
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial import Client, Profile, Timing, load_profiles
from mcintosh_serial.dialects import DIALECTS, get_dialect
from mcintosh_serial.testing import FakeMA352, FakeMX119, FakeMX160

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcintosh_serial.testing._base import FakeUnit

ROOT = Path(__file__).parent.parent
FAST = Timing(
    command=0.5, query=1.0, power=2.0, settle=0.05, settle_max=0.5, retry_delay=0.02
)
PROFILES = sorted(load_profiles().values(), key=lambda p: p.id)

# One emulator per command style. A new dialect adds its emulator here.
EMULATORS: dict[str, Callable[[], FakeUnit]] = {
    "zoned": FakeMX119,
    "simple": FakeMA352,
    "bang": FakeMX160,
}


def _table_rows() -> dict[str, tuple[str, ...]]:
    text = (ROOT / "docs" / "devices.md").read_text()
    rows = re.findall(
        r"^\| (\w+) \| (\w+) \| (\w+) \| (\d+) \| (\d+) \|$", text, re.MULTILINE
    )
    return {
        model.lower(): (status, dialect, baud, zones)
        for model, status, dialect, baud, zones in rows
    }


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_model_is_listed_in_the_docs_with_matching_details(
    profile: Profile,
) -> None:
    row = _table_rows().get(profile.id)
    assert row is not None, f"add {profile.id} to docs/devices.md"
    assert row == (
        profile.status,
        profile.dialect,
        str(profile.baudrate),
        str(len(profile.zones)),
    )


def test_the_docs_list_no_model_without_a_file() -> None:
    assert set(_table_rows()) == {p.id for p in PROFILES}


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_every_model_says_where_its_information_came_from(profile: Profile) -> None:
    assert profile.documents or profile.references, (
        f"{profile.id}: add [references] to its model file"
    )


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
def test_a_model_is_only_verified_when_a_capture_proves_it(profile: Profile) -> None:
    captures = list((ROOT / "tests" / "captures").glob(f"{profile.id}-*.jsonl"))
    assert (profile.status != "verified") or captures, (
        f"{profile.id}: verified needs a capture"
    )


@pytest.mark.parametrize("dialect", sorted(DIALECTS))
def test_every_command_style_is_documented_and_has_an_emulator(dialect: str) -> None:
    assert (ROOT / "docs" / "protocols" / f"{dialect}.md").exists()
    assert dialect in EMULATORS, f"add an emulator for {dialect} to EMULATORS"


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.id)
async def test_the_models_command_style_can_drive_it_end_to_end(
    profile: Profile,
) -> None:
    driven = Client(EMULATORS[profile.dialect](), get_dialect(profile.dialect), FAST)
    await driven.start()
    assert driven.state.zone(1).power is True

    level = min(12, profile.volume_max or 12)
    await driven.set_volume(1, level)
    await driven.set_mute(1, muted=True)
    assert driven.state.zone(1).volume == level
    assert driven.state.zone(1).muted is True
    if profile.inputs:
        lowest = min(profile.inputs)
        await driven.select_input(1, lowest)
        assert driven.state.zone(1).input == lowest
    await driven.stop()
