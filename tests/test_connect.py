"""The one-call setup, the dialect registry and the client factory."""

import asyncio
import dataclasses
from typing import TYPE_CHECKING

import pytest

from mcintosh_serial import (
    Client,
    Timing,
    client_for,
    connection as connection_module,
    get_profile,
)
from mcintosh_serial.connection import connect
from mcintosh_serial.dialects import get_dialect
from mcintosh_serial.errors import McIntoshError
from mcintosh_serial.testing import FakeMX119

if TYPE_CHECKING:
    from mcintosh_serial.transport import Transport

FAST = Timing(
    command=0.2, query=0.3, power=0.5, settle=0.02, settle_max=0.2, retry_delay=0.01
)


def fast_profile(model: str = "mx119"):  # noqa: ANN201
    return dataclasses.replace(get_profile(model), timing=FAST)


def test_unknown_dialect_names_the_known_ones() -> None:
    with pytest.raises(
        ValueError, match=r"unknown dialect 'klingon' \(known: bang, simple, zoned\)"
    ):
        get_dialect("klingon")


async def test_client_for_uses_the_models_dialect_and_timing() -> None:
    client = client_for(FakeMX119(), get_profile("mx119"))
    assert isinstance(client, Client)
    assert client.dialect.name == "zoned"
    await client.stop()


async def test_connect_opens_the_port_at_the_models_baud_rate_and_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, int]] = []

    async def fake_open(url: str, baud: int) -> Transport:
        opened.append((url, baud))
        return FakeMX119()

    monkeypatch.setattr(connection_module, "open_serial", fake_open)
    monkeypatch.setattr(connection_module, "get_profile", fast_profile)
    client = await connect("/dev/ttyUSB0", "mx119")
    assert opened == [("/dev/ttyUSB0", 9600)]
    assert client.connected
    assert client.state.zone(1).volume == 8
    await client.stop()

    await (await connect("/dev/ttyUSB0", "mx119", baudrate=19200)).stop()
    assert opened[-1] == ("/dev/ttyUSB0", 19200)


async def test_connect_closes_the_port_when_the_unit_does_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Mute:
        closed = False

        async def read(self) -> bytes:
            await asyncio.sleep(10)
            return b""

        async def write(self, data: bytes) -> None:
            """Ignore."""

        async def close(self) -> None:
            Mute.closed = True

    async def fake_open(_url: str, _baud: int) -> Transport:
        return Mute()

    monkeypatch.setattr(connection_module, "open_serial", fake_open)
    monkeypatch.setattr(connection_module, "get_profile", fast_profile)
    with pytest.raises(McIntoshError):
        await connect("x", "mx119")
    assert Mute.closed


async def test_connect_rejects_an_unknown_model() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        await connect("x", "mx999")
