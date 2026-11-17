# Agent instructions

These rules apply to any AI coding agent or assistant working in this repository, including when reviewing changes. When a rule conflicts with a task, stop and ask the maintainer instead of working around it.

## Licence

- This project is licensed **`MIT`**. `pyproject.toml` must declare `license = "MIT"`.
- Never modify, shorten or replace `LICENSE`.

## Where protocol knowledge comes from

- Everything in `src/` is either written from scratch or derived from traffic captured on real hardware, which is recorded in `docs/protocols/`. Keep those notes in step with the code: a behavior that is not written down there is not verified.
- Mark anything not seen on a real unit as untested, in the code, the docs and the README. Do not describe a model as supported until someone has confirmed it on that hardware.
- Do not paste code from other projects unless its licence is permissive (MIT, BSD, Apache-2.0, ISC) and you keep its copyright notice and credit it in `README.md`. The existing McIntosh projects credited there were read for protocol knowledge only; no code was copied. Do not reproduce code from memory of other projects.
- McIntosh's RS-232 application note and owner's manuals are not redistributed here. Describe the protocol in your own words and cite the source.

## Dependencies

- Runtime dependencies must be MIT, BSD, Apache-2.0, ISC or similarly permissive, and must stay few. Ask the maintainer before adding one.
- Dev tools are pinned to exact versions in `pyproject.toml`; Dependabot updates them.

## Names and trademarks

- "McIntosh" is another party's name and trademark. This project is independent and not affiliated with or endorsed by McIntosh Laboratory. Use the name only to describe compatibility. Keep the not-affiliated statement in `README.md`.

## Upstream projects

- Do not open issues, pull requests or comments on other projects from this repository without the maintainer asking for it. Draft the text and show it first.

## Code style

- Python 3.14, `uv`, `ruff` with `select = ["ALL"]`, `pyright` in strict mode, and a 100% branch-coverage floor. All four run in CI. Do not weaken a rule or lower the coverage floor to land a change; delete code that cannot be reached instead.
- Prefer functional style: return new values (frozen dataclasses, `replace`) instead of mutating arguments. Use comprehensions over loops that build collections.
- Boolean parameters are keyword-only.

## Tests

Tests exercise the library the way a user would: through its public API (`mcintosh_serial` and `mcintosh_serial.testing`).

- Drive behavior through `ZonedClient` against `FakeMX119`, or over a pseudo-terminal for the real transport. Check results through state, return values, exceptions and what the fake received.
- The emulator copies behavior seen on a real unit. When the real unit does something the emulator does not, add the behavior to the emulator first, then the test, and note it in `docs/protocols/`.
- `tests/acceptance/` holds user-journey tests that import the library only as an installed package. CI runs them against the built wheel, so they must not import from `src/` or use relative paths.

## Releases

- Version lives in `pyproject.toml`. A release is a `chore(release): X.Y.Z` commit that bumps it and updates `CHANGELOG.md`, then a signed annotated tag `vX.Y.Z` whose message is the release notes. Pushing the tag publishes to PyPI and creates the GitHub release; see `.github/workflows/release.yml`.
- Never publish to PyPI by hand.
