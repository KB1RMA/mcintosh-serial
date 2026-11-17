# mcintosh-serial

[![PyPI](https://img.shields.io/pypi/v/mcintosh-serial)](https://pypi.org/project/mcintosh-serial/)
[![CI](https://github.com/KB1RMA/mcintosh-serial/actions/workflows/ci.yml/badge.svg)](https://github.com/KB1RMA/mcintosh-serial/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/KB1RMA/mcintosh-serial/graph/badge.svg)](https://codecov.io/gh/KB1RMA/mcintosh-serial)
[![License: MIT](https://img.shields.io/github/license/KB1RMA/mcintosh-serial)](LICENSE)

Async Python library for controlling McIntosh receivers, preamps and amplifiers over their RS232 port.
It is the protocol layer behind [ha-mcintosh-serial](https://github.com/KB1RMA/ha-mcintosh-serial), a Home
Assistant integration, but has no Home Assistant dependency.

This project is independent. It is not affiliated with or endorsed by McIntosh Laboratory.

> **Status:** early. McIntosh has used three different serial command styles, and the library speaks all three.
> **Only the MX119 is verified on real hardware.** Other models are built from documents and other projects'
> reports, and are labeled `reported` or `untested` in [docs/devices.md](docs/devices.md). Help turning those into
> `verified` is the most useful contribution: see [adding a device](docs/adding-a-device.md).

## Usage

```python
import asyncio

from mcintosh_serial import connect


async def main() -> None:
    client = await connect(
        "/dev/ttyUSB0", "mx119"
    )  # opens the port at the model's baud rate and starts
    print(client.state.zone(1))

    await client.set_volume(1, 12)
    await client.select_input(1, 4)
    await client.set_mute(1, muted=True)

    client.add_listener(print)  # changes made on the unit are pushed to you
    await asyncio.sleep(60)
    await client.stop()


asyncio.run(main())
```

`connect` takes a model id (`mcintosh-serial models` lists them) and works the same for every command style. A
model's settings (baud rate, zones, input names) are in `mcintosh_serial.get_profile("mx119")`.

Volume is the unit's own step number, and input numbers are the unit's own too. Input names are in the model's
profile, but owners can relabel inputs in a unit's menu, so treat them as defaults.

The client sends one command at a time and waits for the unit to finish talking before the next, because some units
drop commands that arrive while they are still replying. Commands raise `McIntoshTimeoutError`,
`McIntoshCommandError` (the unit rejected it) or `McIntoshConnectionError`.

### Serial links

`open_serial` (used by `connect`) opens a device path or a URL with [serialx](https://github.com/puddly/serialx), the
serial driver Home Assistant uses. That covers `socket://host:port` and `rfc2217://host:port` for network serial
servers and, inside Home Assistant, `esphome-hass://` URLs for the serial ports of ESPHome devices such as the Home
Assistant Connect AUX-2. The baud rate is passed along where the link supports it (device paths and ESPHome serial
proxies); a `socket://` server has its own fixed baud rate.

Outside Home Assistant you can reach an ESPHome device's serial proxy directly with
`pip install "mcintosh-serial[esphome]"` and a URL such as
`esphome://192.168.1.42:6053/?port_name=RS-232%20Port%201&key=...`.

You can also give a `Client` any object with `read`, `write` and `close` (the `Transport` protocol), for example
streams from another serial library.

### Testing code that uses the library

`mcintosh_serial.testing` has in-process emulations of units (`FakeMX119`, `FakeMA352`, `FakeMX160`) that implement
the transport interface, and `ReplayTransport`, which plays a recorded capture back. Hand any of them to a `Client`.

## Supported models

| Command style | Looks like | Models |
|---|---|---|
| zoned | `(PON Z1)`, `(VST Z1 8)`, `(CTL 1)` | MX119 (**verified**); C2500; MX120, MX132, MA5200 (untested) |
| simple | `(PWR 1)`, `(VOL 65)`, `(STA 1)` | MA352, MA5300 (reported) |
| bang | `!POWER?`, `!VOL(25)`, `!SRC(3)` | MX160 (reported); MX170, MX180 (untested) |

The full table with status, baud rate and zones is [docs/devices.md](docs/devices.md); it is checked against the model
files by the tests. What was observed on real hardware is in [docs/protocols/](docs/protocols/).

### Is your model missing, or does it not work?

Two commands, no code:

```bash
mcintosh-serial detect /dev/ttyUSB0           # which command style does it speak?
mcintosh-serial capture /dev/ttyUSB0 --model mx119   # record a safe session to paste into an issue
```

Neither changes volume, input, mute or power, and the report hides your serial number. Then open a
[new device issue](https://github.com/KB1RMA/mcintosh-serial/issues/new?template=new-device.yml). Adding a model that
speaks a known style is a small data file; [docs/adding-a-device.md](docs/adding-a-device.md) walks through it.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest            # 100% branch coverage is required
```

`tests/acceptance/` runs against the built wheel in CI. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[AGENTS.md](AGENTS.md) for the project rules.

## Credits

Protocol knowledge comes from McIntosh's RS-232 application note and from reading
[node-mcintosh](https://github.com/stefan747/node-mcintosh),
[hass-mcintosh](https://github.com/homeassistant-projects/hass-mcintosh),
[mcintosh-ma352-hass](https://github.com/felix920506/mcintosh-ma352-hass) and
[esphome-mcintosh-ma5300](https://github.com/The-sultan/esphome-mcintosh-ma5300). No code was copied from them.

## Licence

MIT. See [LICENSE](LICENSE).
