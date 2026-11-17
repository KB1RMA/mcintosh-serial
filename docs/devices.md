# Supported models

How well each model is known. The **status** is the honest part:

- **verified**: confirmed on real hardware with this library.
- **reported**: another project says it works on real hardware; not yet confirmed here.
- **untested**: built from a document or an assumption. It may not work.

The table is checked against `src/mcintosh_serial/models/` by the tests, so it cannot drift.

| Model | Status | Command style | Baud | Zones |
|---|---|---|---|---|
| MX119 | verified | zoned | 9600 | 2 |
| MX120 | untested | zoned | 9600 | 2 |
| MX132 | untested | zoned | 9600 | 2 |
| C2500 | reported | zoned | 115200 | 1 |
| MA5200 | untested | zoned | 115200 | 1 |
| MA352 | reported | simple | 115200 | 1 |
| MA5300 | reported | simple | 115200 | 1 |
| MX160 | reported | bang | 115200 | 2 |
| MX170 | untested | bang | 115200 | 2 |
| MX180 | untested | bang | 115200 | 2 |

Command styles are described in [docs/protocols/](protocols/). Missing your model? See
[adding a device](adding-a-device.md). Most requests only need you to run one command and paste what it prints.
