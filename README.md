# mcintosh-serial

[![PyPI](https://img.shields.io/pypi/v/mcintosh-serial)](https://pypi.org/project/mcintosh-serial/)
[![CI](https://github.com/KB1RMA/mcintosh-serial/actions/workflows/ci.yml/badge.svg)](https://github.com/KB1RMA/mcintosh-serial/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/KB1RMA/mcintosh-serial/graph/badge.svg)](https://codecov.io/gh/KB1RMA/mcintosh-serial)
[![License: MIT](https://img.shields.io/github/license/KB1RMA/mcintosh-serial)](LICENSE)

Async Python library for controlling McIntosh receivers, preamps and amplifiers over their RS232 port.
It is the protocol layer behind [ha-mcintosh-serial](https://github.com/KB1RMA/ha-mcintosh-serial), a Home
Assistant integration, but has no Home Assistant dependency.

This project is independent. It is not affiliated with or endorsed by McIntosh Laboratory.

> **Status:** early. Only the *zoned* command style is implemented, and it has been verified on one unit, a
> McIntosh MX119. Other models are listed below as planned, not supported.

## Usage

```python
import asyncio

from mcintosh_serial import ZonedClient, open_serial


async def main() -> None:
    client = ZonedClient(await open_serial("/dev/ttyUSB0", 9600))
    await client.start()  # enables RS232 control if needed and loads full state
    print(client.state.zone(1))

    await client.set_volume(1, 12)
    await client.select_input(1, 4)
    await client.set_mute(1, muted=True)

    client.add_listener(print)  # changes made on the unit are pushed to you
    await asyncio.sleep(60)
    await client.stop()


asyncio.run(main())
```

`open_serial` takes a device path or a pyserial URL such as `socket://host:port` for a network serial server.
Volume is the unit's own step number; input numbers are the unit's own too (on an MX119, 0 Tuner, 1 PH/AUX,
2 CD 2, 3 SAT, 4 TV, 5 DVD, 6 VCR 1, 7 Tape 1, unless relabeled in its menu).

The client sends one command at a time and waits for the unit to finish talking before the next, because the
unit drops commands that arrive while it is still replying. Commands raise `McIntoshTimeoutError`,
`McIntoshCommandError` (the unit answered `(ERR n)`) or `McIntoshConnectionError`.

### Testing code that uses the library

`mcintosh_serial.testing.FakeMX119` is an in-process emulation of the unit, built from captured traffic. It
implements the transport interface, so you can hand it straight to `ZonedClient`.

## Command styles

McIntosh has used three different serial command styles. They are not interchangeable.

| Style | Looks like | Models | Status |
|---|---|---|---|
| zoned | `(PON Z1)`, `(VST Z1 8)`, `(CTL 1)` | MX119 (verified); C47, C2500, MA5200 per McIntosh's application note | implemented, MX119 only |
| simple | `(PWR 1)`, `(VOL 65)`, `(STA 1)` | MA352, MA5300 | planned, untested |
| bang | `!POWER?`, `!VOL(n)`, `!SRC(n)` | MX160, MX170, MX180 | planned, untested |

What was observed on a real MX119 (wiring, baud rate, timing, quirks) is in
[docs/protocols/zoned.md](docs/protocols/zoned.md). If you have a McIntosh unit and can help test or have
protocol documents, please open an issue.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest            # 100% branch coverage is required
```

`tests/acceptance/` runs against the built wheel in CI. See [AGENTS.md](AGENTS.md) for the project rules.

## Credits

Protocol knowledge comes from McIntosh's RS-232 application note and from reading
[node-mcintosh](https://github.com/stefan747/node-mcintosh),
[hass-mcintosh](https://github.com/homeassistant-projects/hass-mcintosh),
[mcintosh-ma352-hass](https://github.com/felix920506/mcintosh-ma352-hass) and
[esphome-mcintosh-ma5300](https://github.com/The-sultan/esphome-mcintosh-ma5300). No code was copied from them.

## Licence

MIT. See [LICENSE](LICENSE).
