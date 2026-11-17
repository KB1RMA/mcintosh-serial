## What this changes

<!-- A new model file? A new command style? A fix? -->

## For a new or changed model

- [ ] `src/mcintosh_serial/models/<model>.toml` added or updated, with an honest `status`
- [ ] Row added to `docs/devices.md`
- [ ] A capture and `.expected.json` added under `tests/captures/` (needed to claim `verified`)
- [ ] Where the information came from is in the model file's `references`

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run pyright`
- [ ] `uv run pytest` (100% coverage)
