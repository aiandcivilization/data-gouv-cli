# Contributing

Thanks for taking the time to improve `data-gouv-cli`.

## Setup

```bash
git clone <this repository>
cd <repository>
uv sync
uv run data-gouv-cli --help
```

## Before opening a pull request

```bash
uv run ruff check .
uv run pytest -q
uv build
```

Keep one change per pull request. Add a test for a new command or a changed
output. Do not commit credentials, tokens or private endpoints.
