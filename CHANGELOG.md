# Changelog

All notable changes are listed here. The format follows the style of the project's other
repositories: one section per release, generated from conventional commits.

## Unreleased

### Features

* the zoned dialect, verified on a McIntosh MX119: power, volume, mute and input selection, status pushed by the unit
* an async client that paces commands, retries a query rejected just after power-up and reports connection loss
* `mcintosh_serial.testing.FakeMX119`, an in-process emulation built from traffic captured on a real unit
