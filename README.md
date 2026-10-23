<p align="center">
  <img src="docs/logo.svg" width="104" alt="french-gov-cli">
</p>

<h1 align="center">french-gov-cli</h1>

<p align="center">
  <b>Your agent's interface to French public data.</b><br>
  One search costs 522 tokens instead of 22,187.<br>
  No MCP server, no schema dump, no 900 MB download.
</p>

<p align="center">
  <a href="https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml"><img src="https://github.com/aiandcivilization/french-gov-cli/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12%E2%80%933.15-blue" alt="Python 3.12–3.15">
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
  <a href="https://github.com/aiandcivilization/french-gov-cli/stargazers"><img src="https://img.shields.io/github/stars/aiandcivilization/french-gov-cli?style=flat" alt="Stars"></a>
</p>

<p align="center">
  <a href="docs/demo.mp4"><img src="docs/demo.gif" width="900" alt="french-gov-cli demo"></a>
</p>

## The problem

An agent that needs one number from `data.gouv.fr` usually pays for the whole
catalogue: a server to install, a tool schema in the context, a JSON payload
with forty fields, then a ZIP download.

The same search, measured with `o200k_base`:

| What the model reads | Tokens |
|---|---|
| Raw `data.gouv.fr` API JSON, 3 datasets | 22,187 |
| `french-gov-cli search-datasets`, 3 datasets | **522** |

42× less context for the same three datasets, before the model reads a single
row. The CLI projects the seven fields an agent actually uses, prints them as
TOON, and exits. No handshake, no schema, no server.

<details>
<summary>How the tokens were counted</summary>

```bash
curl -s "https://www.data.gouv.fr/api/1/datasets/?q=zonage%20ABC&page_size=3" > raw.json
french-gov-cli search-datasets "zonage ABC" --page-size 3 > cli.txt
python -c "import tiktoken,sys; e=tiktoken.get_encoding('o200k_base'); \
  print(len(e.encode(open(sys.argv[1]).read())))" raw.json cli.txt
# 22187  522
```

`o200k_base` is a public tokenizer, not Claude's; it is used here because it is
reproducible. The ratio holds across tokenizers because the CLI removes fields,
keys and punctuation.
</details>

## What makes it small

- **Projection, not passthrough.** `search-datasets` returns `id`, `title`,
  `organization`, `tags`, `resources_count`, `first_resource_url`, `url` — not
  the forty fields of the API object.
- **TOON output.** One header, one row per line, no braces, no quotes, no
  repeated keys.
- **SQL in place.** `query` runs DuckDB over HTTP range requests, so an 878 KB
  CSV is read, not downloaded. A 200 MB ZIP member costs one range read.
- **One process per task.** Nothing stays resident, nothing is registered in
  the agent's tool list, nothing has to be discovered first.

## Install

```bash
uv tool install "git+https://github.com/aiandcivilization/french-gov-cli.git"
```

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 to 3.15.

<details>
<summary>Other ways to install</summary>

```bash
# pipx
pipx install "git+https://github.com/aiandcivilization/french-gov-cli.git"

# run without installing
uvx --from "git+https://github.com/aiandcivilization/french-gov-cli.git" french-gov-cli --help

# from source
git clone https://github.com/aiandcivilization/french-gov-cli.git
cd french-gov-cli && uv sync && uv run french-gov-cli --help

# with the remote-ZIP extra
uv tool install "french-gov-cli[remote] @ git+https://github.com/aiandcivilization/french-gov-cli.git"
```
</details>

## 30-second tour

Search, then ask for the files:

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
source: "https://static.data.gouv.fr/resources/liste-des-communes-selon-le-zonage-abc/..."
format: csv
strategy: httpfs_direct
rows_returned: 5
cache_dir: /home/ubuntu/.cache/french-gov-cli
columns[2]: zone,communes
rows[5,]{zone,communes}:
  C,28326
  B2,3162
  B1,2383
  A,870
  Abis,134
```

28,326 communes sit in zone C, 870 in the tightest zone A. The file is 878 KB
and was read remotely, column by column.

## Commands

| Command | What it does |
|---|---|
| `search-datasets` | Search datasets, resource URLs included. |
| `dataset` | Detailed metadata for one dataset. |
| `dataset-resources` | List the resources of a dataset with their download URLs. |
| `resolve` | Resolve a dataset into ready-to-use file URLs in one call. |
| `resource` | Detailed metadata for one resource. |
| `query` | Run SQL over a remote or local CSV, Parquet, JSON or ZIP member. |
| `query-resource` | Query rows through the data.gouv.fr tabular API. |
| `download-resource` | Stream a resource to disk with optional conversion. |
| `api` | Call any JSON API and print the answer as TOON. |
| `search-dataservices` | Search the third-party APIs catalogued on data.gouv.fr. |
| `dataservice` | Detailed metadata for a third-party API. |
| `dataservice-openapi` | Fetch and summarize the OpenAPI spec of a third-party API. |
| `search-orgs` | Search publishing organizations. |
| `org` | Detailed metadata for an organization. |
| `metrics` | Usage metrics for a dataset, resource or organization. |

`query` returns at most 50 rows unless you pass `--limit`. Run
`french-gov-cli <command> --help` for the flags of one command.

## Recipes

<details>
<summary><b>Find every file of a dataset</b></summary>

```bash
french-gov-cli resolve 6564969d3579e21795ebd378
```

Returns the dataset metadata and a table of resources: id, title, format, size,
URL, and whether the tabular API can serve it.
</details>

<details>
<summary><b>Query a remote ZIP member</b></summary>

```bash
french-gov-cli query \
  "https://data.grandpoitiers.fr/data-fair/api/v1/datasets/offre-de-transport-du-reseau-vitalis/metadata-attachments/gtfs.zip" \
  --member "stops.txt" \
  --sql "SELECT stop_name FROM data LIMIT 3"
```

With the `remote` extra installed, only the member's byte range is fetched
(`strategy: zip_range`). Without it, the archive is downloaded once. A wrong
member name prints every available member.
</details>

<details>
<summary><b>Excel resources</b></summary>

DuckDB cannot query an `.xlsx` in place. Convert it once, then query the CSV:

```bash
french-gov-cli download-resource <resource-id> --format csv --dest ./data
french-gov-cli query ./data/<downloaded>.csv --sql "SELECT * FROM data LIMIT 5"
```
</details>

<details>
<summary><b>Call any JSON API</b></summary>

```bash
french-gov-cli api "https://www.data.gouv.fr/api/1/datasets/?q=eau&page_size=2"
```

The payload is printed as TOON, so pagination and nested objects stay readable
in a terminal.
</details>

<details>
<summary><b>Download a resource for offline work</b></summary>

```bash
french-gov-cli download-resource <resource-id> --dest ./data
```

`--dest` defaults to `./downloads` in the current directory.
</details>

<details>
<summary><b>Check how a dataset is used</b></summary>

```bash
french-gov-cli metrics datasets 6564969d3579e21795ebd378 --limit 2
```

`dataservice-openapi` only answers for the catalogued APIs that publish an
`openapi_url`. When none exists it prints `note: No OpenAPI spec URL available.`
</details>

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FRENCH_GOV_CACHE` | `~/.cache/french-gov-cli` | Where downloaded files and remote reads are cached. |
| `DATAGOUV_API_ENV` | `prod` | `prod` for data.gouv.fr, `demo` for the demo environment and tabular preproduction. |

Both are optional; `.env.example` lists them if you prefer a file. No token, no
credential, no account.

## Output format

Every command prints [TOON](https://github.com/toon-format/toon). A table has a
header line with the columns, then one row per line:

```text
columns[2]: zone,communes
rows[2,]{zone,communes}:
  C,28326
  A,870
```

A single object is printed as `key: value` lines. `query` adds five metadata
lines before its table (`source`, `format`, `strategy`, `rows_returned`,
`cache_dir`), and `api` adds the pagination keys of the endpoint. There is no
`--json` flag on purpose: one format, one code path, one thing to read.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest -q
uv build
```

The test suite is a smoke test: the console script exists and `--help` exits
0. A test that exercises one live search is the obvious next contribution.

## License

MIT © Yanis Labeyrie

Data comes from [data.gouv.fr](https://www.data.gouv.fr) and keeps its own
licence, usually Licence Ouverte 2.0. Check the dataset metadata before
republishing.
