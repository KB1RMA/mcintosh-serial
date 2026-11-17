# Changelog

## [0.3.0](https://github.com/KB1RMA/mcintosh-serial/compare/v0.2.0...v0.3.0) (2026-11-17)


### Features

* one generic `Client` for every command style, with a `Dialect` interface, so the library now speaks the MX119 (zoned), MA352 and MA5300 (simple) and MX160, MX170 and MX180 (bang) styles; only the MX119 is verified on hardware ([2ff90f5](https://github.com/KB1RMA/mcintosh-serial/commit/2ff90f5))
* model profiles as TOML files (`mcintosh_serial/models/`): ten models so far, each labeled `verified`, `reported` or `untested`
* `connect(url, model)` opens the port at the model's baud rate and returns a started client
* the `mcintosh-serial` command: `models`, `detect` (which command style does a unit speak?) and `capture` (a safe, serial-number-redacted session for a "new device" issue)
* `Client.begin()`, `detect()`, capture recording (`RecordingTransport`) and `ReplayTransport`, so a contributor's capture becomes a regression test
* emulators for the simple (`FakeMA352`) and bang (`FakeMX160`) styles, and a conformance suite that runs every model file against its style's emulator
* contributor guide, issue forms and a pull request template
* `Timing.volume` (volume sets, longer for the MA352 and MA5300, which ramp) and `Timing.optional` (optional queries, so unanswered ones cost about a second each)
* `Dialect.after_power()`: the simple style turns status reporting on after power-on when the client started in standby


### Changed

* `McIntoshCommandError` no longer mentions `(ERR n)`, since other styles report errors differently; `code` is the unit's error code or text
* `Command`'s `skip_if` and `required` are keyword-only
* `FakeMX119` moved into the `mcintosh_serial.testing` package (the import path is unchanged)

## [0.2.0](https://github.com/KB1RMA/mcintosh-serial/compare/v0.1.0...v0.2.0) (2026-11-17)


### Features

* open serial ports with serialx, the driver Home Assistant uses, so a Home Assistant Connect AUX-2 or any ESPHome serial proxy can be used from Home Assistant (`esphome-hass://` URLs), and `socket://` and `rfc2217://` network serial servers work too ([860f365](https://github.com/KB1RMA/mcintosh-serial/commit/860f365))
* an optional `esphome` extra for reaching an ESPHome serial proxy directly (`esphome://` URLs) outside Home Assistant


### Dependencies

* replace pyserial-asyncio-fast with serialx (>=1.11.0, the version Home Assistant pins)

## [0.1.0](https://github.com/KB1RMA/mcintosh-serial/releases/tag/v0.1.0) (2026-11-16)


### Features

* the zoned dialect, verified on a McIntosh MX119: power, volume, mute and input selection, with changes made on the unit pushed to the client
* an async `ZonedClient` that paces commands, retries a query rejected just after power-up and reports connection loss
* `open_serial` for device paths and pyserial URLs such as `socket://host:port`
* `mcintosh_serial.testing.FakeMX119`, an in-process emulation of the unit built from traffic captured on real hardware
