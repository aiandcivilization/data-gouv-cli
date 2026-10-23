# 🇫🇷 french-gov-cli

> Search, inspect and query data.gouv.fr from your terminal — including SQL over a remote CSV without downloading it.

[![CI](https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

## Table of Contents

- [Why](#why)
- [Demo](#demo)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Recipes](#recipes)
- [Configuration](#configuration)
- [Output format](#output-format)
- [Development](#development)
- [License](#license)

## Why

data.gouv.fr hosts French public data: population, housing, water quality,
subsidies, company registries. The website is good for browsing and bad for
getting one number out of it. You click through a dataset page, land on a ZIP,
download 700 MB, open a spreadsheet, and only then discover the column you
needed.

This CLI turns that into commands:

- find a dataset and its resources in one call;
- run SQL against a remote CSV, XLSX or Parquet file over HTTP range requests,
  so a 900 MB file costs one range read, not a download;
- read a member of a remote ZIP the same way;
- get every answer as TOON, a compact tabular format that an LLM reads without
  burning context on JSON punctuation.

No API key. No account. Public data only.

## Demo

[![french-gov-cli demo](docs/demo.gif)](docs/demo.mp4)

*A 20-second tour: search, inspect, then SQL over a remote CSV.*

## Installation

### uv (recommended)

```bash
uv tool install "git+https://github.com/aiandcivilization/french-gov-cli.git"
```

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

### pipx

```bash
pipx install "git+https://github.com/aiandcivilization/french-gov-cli.git"
```

### Run without installing

```bash
uvx --from "git+https://github.com/aiandcivilization/french-gov-cli.git" french-gov-cli --help
```

### From source

```bash
git clone https://github.com/aiandcivilization/french-gov-cli.git
cd french-gov-cli
uv sync
uv run french-gov-cli --help
```

### Optional: read a member of a remote ZIP

```bash
uv tool install "french-gov-cli[remote] @ git+https://github.com/aiandcivilization/french-gov-cli.git"
```

## Quick start

Search, then ask for the files of the dataset you picked:

```bash
french-gov-cli search-datasets "zonage ABC" --page-size 3
french-gov-cli dataset-resources 656715871172d08f8f680063
```

Run SQL on a remote CSV — nothing is downloaded:

```bash
french-gov-cli query \
  "https://static.data.gouv.fr/resources/liste-des-communes-selon-le-zonage-abc/20260703-091314/liste-ensemble-des-communes-zonage-abc-en-vigueur-26-juin-2026.csv" \
  --sql 'SELECT "Zonage ABC en vigueur depuis le 26 juin 2026" AS zone, count(*) AS communes
         FROM data GROUP BY 1 ORDER BY 2 DESC'
```

```text
rows_returned: 5
columns[2]: zone,communes
rows[5,]{zone,communes}:
  C,28326
  B2,3162
  B1,2383
  A,870
  Abis,134
```

28,326 communes are in zone C, 870 in the tightest zone A. The file is 878 KB
and was read remotely, column by column.

## Commands

| Command | What it does |
|---|---|
| `search-datasets` | Search datasets, resource URLs included. |
| `dataset` | Detailed metadata for one dataset. |
| `dataset-resources` | List the resources of a dataset with their download URLs. |
| `resolve` | Resolve a dataset into ready-to-use file URLs in one call. |
| `resource` | Detailed metadata for one resource. |
| `query` | Run SQL over a remote or local CSV, XLSX, Parquet, JSON or ZIP member. |
| `query-resource` | Query rows through the data.gouv.fr tabular API. |
| `download-resource` | Stream a resource to disk with optional conversion. |
| `api` | Call any JSON API and print the answer as TOON. |
| `search-dataservices` | Search the third-party APIs catalogued on data.gouv.fr. |
| `dataservice` | Detailed metadata for a third-party API. |
| `dataservice-openapi` | Fetch and summarize the OpenAPI spec of a third-party API. |
| `search-orgs` | Search publishing organizations. |
| `org` | Detailed metadata for an organization. |
| `metrics` | Usage metrics for a dataset, resource or organization. |

Run `french-gov-cli <command> --help` for the options of one command.

## Recipes

### Find every file of a dataset

```bash
french-gov-cli resolve 6564969d3579e21795ebd378
```

`resolve` returns the dataset metadata and a table of resources: id, title,
format, size, URL, and whether the tabular API can serve it.

### Query a remote ZIP member

```bash
french-gov-cli query "https://static.data.gouv.fr/resources/.../dis-2026-dept.zip" \
  --member "dis-2026-dept.csv" \
  --sql "SELECT * FROM data LIMIT 5"
```

With `remotezip` installed, only the member's byte range is fetched.

### Call any JSON API

```bash
french-gov-cli api "https://www.data.gouv.fr/api/1/datasets/?q=eau&page_size=2"
```

`api` prints the JSON payload as TOON, so pagination and nested objects stay
readable in a terminal.

### Download a resource for offline work

```bash
french-gov-cli download-resource <resource-id> --dest ./data
```

### Check how a dataset is used

```bash
french-gov-cli metrics datasets 6564969d3579e21795ebd378 --limit 2
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FRENCH_GOV_CACHE` | `~/.cache/french-gov-cli` | Where downloaded files and remote reads are cached. |
| `DATAGOUV_API_ENV` | `prod` | `prod` for data.gouv.fr, `demo` for the demo environment and tabular preproduction. |

No token, no credential, no config file. The tool only reads public data.

## Output format

Every command prints [TOON](https://github.com/toon-format/toon): a header
line with the columns, then one row per line.

```text
columns[2]: zone,communes
rows[2,]{zone,communes}:
  C,28326
  A,870
```

It is the same data as JSON, minus the punctuation, and it is what makes the
output usable inside an agent's context window. There is no `--json` flag on
purpose: one format, one code path, one thing to read.

## Development

```bash
uv sync
uv run ruff check .
uv build
```

There is no test suite yet. A smoke test that runs `--help` and one live
search would be the first contribution.

## License

MIT © Yanis Labeyrie

Data comes from [data.gouv.fr](https://www.data.gouv.fr) and keeps its own
licence, usually Licence Ouverte 2.0. Check the dataset metadata before
republishing.
