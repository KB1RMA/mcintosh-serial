# Adding a McIntosh model

There are three ways to help, from least to most work. You do not need to write code for the first two.

## 1. Open an issue with a capture (any owner, no code)

1. Install the library: `pip install mcintosh-serial` (or `uvx mcintosh-serial ...`).
2. Connect the unit and turn RS-232 control on if its menu has a setting for it.
3. See which command style it speaks. This sends only harmless commands:
   ```bash
   mcintosh-serial detect /dev/ttyUSB0
   ```
4. Record a capture, using the nearest model from `mcintosh-serial models` (or `--dialect` and `--baud`):
   ```bash
   mcintosh-serial capture /dev/ttyUSB0 --model mx119
   ```
   It never changes volume, input, mute or power. It prints a report with your serial number hidden, and writes a
   `.jsonl` file of the exact bytes.
5. Open a [new device issue](../../../issues/new?template=new-device.yml) and paste the report and attach the file.

## 2. Add a model that uses a known command style (a small PR)

If `detect` found one of the existing styles (zoned, simple, bang), the new model is a data file.

1. Copy the closest file in `src/mcintosh_serial/models/` to `<model>.toml` and edit it: name, baud rate, zones,
   input numbers and names, connector, and where the information came from. Set `status` honestly.
2. Add a row to [docs/devices.md](devices.md). A test fails if the table and the files disagree.
3. If you have the unit, add your capture as `tests/captures/<model>.jsonl` with a `<model>.expected.json` next to it
   (see the docstring in `tests/test_captures.py`). That turns your session into a regression test, and lets us move
   the model to `verified`.
4. Run `uv run pytest`. The conformance tests automatically run every model against the emulator of its command style.

## 3. Add a new command style (a bigger PR)

Only needed when `detect` finds nothing and the unit does answer something.

1. Write the protocol notes first: `docs/protocols/<style>.md`. Say what is confirmed and what is guessed.
2. Add `src/mcintosh_serial/dialects/<style>.py` implementing the `Dialect` interface in `dialects/base.py`: cut the
   stream into frames, apply a frame to the state, build each command with the reply that completes it. Register it in
   `dialects/__init__.py`.
3. Add an emulator in `src/mcintosh_serial/testing/` built from your capture, and register it in
   `tests/test_conformance.py`.
4. Add tests for the dialect and a model file. CI requires 100% coverage, strict typing and `ruff`.

## What "verified" needs

A real unit, this library, and a capture that replays to the right state. Until then a model stays `reported` or
`untested`, and the README says so.
