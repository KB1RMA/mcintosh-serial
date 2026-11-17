"""In-process emulations of McIntosh units, for tests of this library and of code built on it."""

from mcintosh_serial.testing.bang import FakeMX160
from mcintosh_serial.testing.replay import ReplayMismatchError, ReplayTransport
from mcintosh_serial.testing.simple import FakeMA352
from mcintosh_serial.testing.zoned import FakeMX119

__all__ = [
    "FakeMA352",
    "FakeMX119",
    "FakeMX160",
    "ReplayMismatchError",
    "ReplayTransport",
]
