"""Async control of McIntosh equipment over RS232."""

from mcintosh_serial.client import Client, Timing, ZonedClient, client_for
from mcintosh_serial.connection import connect
from mcintosh_serial.errors import (
    McIntoshCommandError,
    McIntoshConnectionError,
    McIntoshError,
    McIntoshTimeoutError,
)
from mcintosh_serial.frames import Frame, parse_frames
from mcintosh_serial.profiles import Profile, get_profile, load_profiles
from mcintosh_serial.state import DeviceInfo, DeviceState, ZoneState
from mcintosh_serial.transport import StreamTransport, Transport, open_serial

__all__ = [
    "Client",
    "DeviceInfo",
    "DeviceState",
    "Frame",
    "McIntoshCommandError",
    "McIntoshConnectionError",
    "McIntoshError",
    "McIntoshTimeoutError",
    "Profile",
    "StreamTransport",
    "Timing",
    "Transport",
    "ZoneState",
    "ZonedClient",
    "client_for",
    "connect",
    "get_profile",
    "load_profiles",
    "open_serial",
    "parse_frames",
]
