# Changelog

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
