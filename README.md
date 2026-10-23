# 🗄️ french-gov-cli

> Clean wrapper around the French government data.gouv.fr APIs (datasets, dataservices, orgs, resources, tabular, metrics).

[![CI](https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml) [![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

## Table of Contents

- [Description](#description)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Development](#development)
- [License](#license)

## Description

Clean wrapper around the French government data.gouv.fr APIs (datasets, dataservices, orgs, resources, tabular, metrics).

<!-- TODO(opensource): add a demo GIF or a short asciinema recording here. -->

## Installation

### uv (recommended)

```bash
uv tool install "git+https://github.com/aiandcivilization/french-gov-cli.git"
```

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

### Run without installing

```bash
uvx --from "git+https://github.com/aiandcivilization/french-gov-cli.git" french-gov-cli --help
```

### pipx

```bash
pipx install "git+https://github.com/aiandcivilization/french-gov-cli.git"
```

### Once the package is on PyPI

```bash
uv tool install french-gov-cli
```

### From source

```bash
git clone https://github.com/aiandcivilization/french-gov-cli.git
cd french-gov-cli
uv sync
uv run french-gov-cli --help
```

## Quick start

```bash
french-gov-cli --help
french-gov-cli search-datasets --help
```

## Commands

| Command | What it does |
|---|---|
| `french-gov-cli search-datasets` | Search datasets on data.gouv.fr (resource URLs included). |
| `french-gov-cli dataset` | Get detailed info about a dataset. |
| `french-gov-cli resolve` | Resolve a dataset into ready-to-use file URLs (one call). |
| `french-gov-cli dataset-resources` | List the resources of a dataset with their download URLs. |
| `french-gov-cli resource` | Get detailed info about a resource. |
| `french-gov-cli query` | Run SQL over a remote or local tabular file without downloading it. |
| `french-gov-cli api` | Call any JSON API and get the answer as TOON. |
| `french-gov-cli query-resource` | Query rows of a resource through the tabular API. |
| `french-gov-cli search-dataservices` | Search the third-party APIs cataloged on data.gouv.fr. |
| `french-gov-cli dataservice` | Get detailed info about a third-party API. |
| `french-gov-cli dataservice-openapi` | Fetch and summarize the OpenAPI spec of a third-party API. |
| `french-gov-cli search-orgs` | Search the publishing organizations. |
| `french-gov-cli org` | Get detailed info about an organization. |
| `french-gov-cli download-resource` | Download a resource (streamed, max speed) with optional auto-conversion. |
| `french-gov-cli metrics` | Get usage metrics for a dataset/resource/org. |
| `french-gov-cli inspect` | Show the tool's own metadata (package, entrypoint, skill, index). |

Run `french-gov-cli <command> --help` for the options of one command.

## Configuration

| Variable | Purpose |
|---|---|
| `DATAGOUV_API_ENV` | <!-- TODO(opensource): describe this variable --> |
| `FRENCH_GOV_CACHE` | <!-- TODO(opensource): describe this variable --> |

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv build
```

## License

MIT © yanis.labeyrie
