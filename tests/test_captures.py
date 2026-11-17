"""Replay every capture in tests/captures against the library.

To add a model's regression test, drop ``name.jsonl`` (from ``mcintosh-serial capture``) and
``name.expected.json`` here; no code is needed. The expected file says which model the capture
is from and what state the library should have after starting:

    {"model": "mx119", "zones": {"1": {"power": true, "input": 3, "volume": 8, "muted": false}}}

``mx119-cold-start`` is a real MX119 session (2026-11-16): the first (QRY) is rejected because
RS232 control is off, (CTL 1) turns it on, and the next (QRY) returns the full status. Times were
not recorded, and the second (ERR 1) is inferred: the library retries a rejected query once.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from mcintosh_serial import Client, Timing, get_profile
from mcintosh_serial.capture import Event, events_from_jsonl
from mcintosh_serial.dialects import get_dialect
from mcintosh_serial.testing import ReplayTransport

CAPTURES = Path(__file__).parent / "captures"
FAST = Timing(
    command=0.5, query=1.0, power=2.0, settle=0.05, settle_max=0.5, retry_delay=0.02
)


def load(capture: Path) -> tuple[dict[str, Any], tuple[Event, ...]]:
    expected: dict[str, Any] = json.loads(
        capture.with_suffix(".expected.json").read_text()
    )
    return expected, events_from_jsonl(capture.read_text())


@pytest.mark.parametrize(
    "capture", sorted(CAPTURES.glob("*.jsonl")), ids=lambda p: p.stem
)
async def test_the_library_reproduces_the_state_in_a_real_capture(
    capture: Path,
) -> None:
    expected, events = load(capture)
    profile = get_profile(expected["model"])
    replay = ReplayTransport(events)
    client = Client(replay, get_dialect(profile.dialect), FAST)

    await client.start()

    for zone, fields in expected["zones"].items():
        state = client.state.zone(int(zone))
        assert {name: getattr(state, name) for name in fields} == fields
    assert replay.finished, (
        "the library stopped before sending everything in the capture"
    )
    await client.stop()
