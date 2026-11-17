"""Model profiles: loading, validation and lookup."""

import tomllib
from typing import TYPE_CHECKING, Any

import pytest

from mcintosh_serial import get_profile, load_profiles, profiles as profiles_module
from mcintosh_serial.profiles import ProfileError, parse_profile

if TYPE_CHECKING:
    from pathlib import Path

VALID = """
id = "x1"
name = "McIntosh X1"
dialect = "zoned"
status = "untested"
baudrate = 9600
connector = "DB9"
zones = [1]
[inputs]
1 = "CD"
"""


def parsed(text: str = VALID) -> dict[str, Any]:
    return tomllib.loads(text)


def test_mx119_profile_is_loaded() -> None:
    profile = get_profile("MX119")  # lookup ignores case
    assert (profile.dialect, profile.baudrate, profile.status) == (
        "zoned",
        9600,
        "verified",
    )
    assert profile.zones == (1, 2)
    assert profile.inputs[3] == "SAT"
    assert profile.documents


def test_unknown_model_lists_the_known_ones() -> None:
    with pytest.raises(ValueError, match=r"unknown model .mx999."):
        get_profile("mx999")


def test_a_valid_profile_parses_with_defaults() -> None:
    profile = parse_profile(parsed(), "x1.toml")
    assert profile.timing.command == 2.0
    assert profile.documents == ()
    assert profile.notes == ""


def test_timing_can_be_overridden_per_model() -> None:
    profile = parse_profile(parsed(VALID + "[timing]\nsettle = 0.1\n"), "x1.toml")
    assert profile.timing.settle == 0.1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('id = "x1"\n', ""), "'id' is required"),
        (('dialect = "zoned"', 'dialect = "klingon"'), "unknown dialect 'klingon'"),
        (('status = "untested"', 'status = "great"'), "status must be one of"),
        (("zones = [1]", "zones = []"), "zones must be a list"),
        (("zones = [1]", "zones = [0]"), "zones must be a list"),
        (('1 = "CD"', 'one = "CD"'), "input numbers must be integers"),
        (("baudrate = 9600", 'baudrate = "fast"'), "'baudrate' is required"),
        (("[inputs]", "[timing]\nsetle = 0.4\n[inputs]"), "unknown timing setle"),
        (("[inputs]", '[timing]\npower = "long"\n[inputs]'), "positive numbers"),
        (("[inputs]", "[timing]\npower = true\n[inputs]"), "positive numbers"),
        (("[inputs]", "[timing]\npower = 0\n[inputs]"), "positive numbers"),
        (("zones = [1]", 'zones = [1]\nvolume_max = "max"'), "volume_max must be"),
        (("zones = [1]", "zones = [1]\nvolume_max = 0"), "volume_max must be"),
    ],
)
def test_invalid_profiles_are_rejected_with_the_file_and_reason(
    change: tuple[str, str], message: str
) -> None:
    with pytest.raises(ProfileError, match=message):
        parse_profile(parsed(VALID.replace(*change)), "x1.toml")


def test_duplicate_model_ids_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.toml").write_text(VALID)
    (models / "b-notes.txt").write_text("ignored")
    (models / "c.toml").write_text(VALID)

    def fake_files(_package: str) -> Path:
        return tmp_path

    monkeypatch.setattr(profiles_module.resources, "files", fake_files)
    load_profiles.cache_clear()
    try:
        with pytest.raises(ProfileError, match="duplicate model id 'x1'"):
            load_profiles()
    finally:
        load_profiles.cache_clear()
