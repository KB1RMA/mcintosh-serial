# Contributing

The most useful contribution is a **capture from a McIntosh model we have not seen**. It takes about two minutes and
needs no code: see [docs/adding-a-device.md](docs/adding-a-device.md).

For code changes:

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest        # 100% branch coverage is required
```

Read [AGENTS.md](AGENTS.md) for the project rules (licensing, trademarks, how to describe what is verified).
Use [conventional commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`...).
