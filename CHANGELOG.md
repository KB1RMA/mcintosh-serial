# Changelog

## [0.1.0](https://github.com/KB1RMA/mcintosh-serial/releases/tag/v0.1.0) (2026-11-16)


### Features

* the zoned dialect, verified on a McIntosh MX119: power, volume, mute and input selection, with changes made on the unit pushed to the client
* an async `ZonedClient` that paces commands, retries a query rejected just after power-up and reports connection loss
* `open_serial` for device paths and pyserial URLs such as `socket://host:port`
* `mcintosh_serial.testing.FakeMX119`, an in-process emulation of the unit built from traffic captured on real hardware
