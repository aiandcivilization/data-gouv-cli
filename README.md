<p align="center">
  <img src="docs/logo.png" width="104" alt="data-gouv-cli">
</p>

<h1 align="center">data-gouv-cli</h1>

<p align="center">
  <b>Your agent's interface to French public data.</b><br>
  One search costs 522 tokens instead of 22,187.<br>
  No MCP server, no schema dump, no 900 MB download.
</p>

<p align="center">
  <a href="https://github.com/aiandcivilization/data-gouv-cli/actions/workflows/ci.yml"><img src="https://github.com/aiandcivilization/data-gouv-cli/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12%E2%80%933.15-blue" alt="Python 3.12–3.15">
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
</p>

<p align="center">
  <a href="docs/demo.mp4"><img src="docs/demo.gif" width="900" alt="data-gouv-cli demo"></a>
</p>

## What you actually ask

> **“What is the median price per m² in Biot?”**

You know the answer is somewhere on `data.gouv.fr`. What you do not know:

- **which dataset** — DVF, INSEE, the notaries, a regional portal?
- **which fields** — forty columns, and the price is a ratio of two of them;
- **which commune code** — `06018`, not “Biot”;
- **whether to download** — the 2024 file is 107 MB; the commune file is a few
  hundred rows.

That is twenty minutes of browsing, or an agent session spent negotiating a
schema. The CLI answers it in one command:

```bash
data-gouv-cli query \
  "https://files.data.gouv.fr/geo-dvf/latest/csv/2024/communes/06/06018.csv" \
  --sql "SELECT round(median(valeur_fonciere / nullif(surface_reelle_bati, 0)), 1) AS eur_per_m2
         FROM data
         WHERE nature_mutation = 'Vente' AND surface_reelle_bati > 9"
```

```text
columns[1]: eur_per_m2
rows[1,]{eur_per_m2}:
  6141.8
```

One row. No 107 MB download, no schema in the context, no field guessing.

## Same question, two paths

An agent can answer the same question through the official data.gouv.fr MCP
server, or through this CLI. We ran both on 23 October 2026 and counted what
the model reads: the tool schema, every request, every response, and the final
answer.

<p align="center">
  <img src="docs/benchmark.svg" width="880" alt="Median price per square metre in Biot: the MCP spends 6,489 tokens and gets no answer; the CLI spends 223 tokens and returns 6,142 euros per square metre. Population: 6 steps and 11,569 tokens versus 3 steps and 1,351 tokens.">
</p>

| Question | Path | Steps | Tokens | Result |
|---|---|---|---|---|
| Population of Biot | data.gouv MCP | 6 | 11,569 | 9,880 (older vintage) |
| | `data-gouv-cli` | 3 | **1,351** | **10,511** (INSEE 2023) |
| Median €/m², Biot 2024 | data.gouv MCP | 3 | 6,489* | no answer |
| | `data-gouv-cli` | 1 | **223** | **6,141.8 €/m²** (238 sales) |

\* including the 2,673-token tool schema, counted once.

The MCP is not slow; it is bounded by its tools. DVF 2024 is not indexed by the
Tabular API, so the server has no path to the answer. On population it falls
back to a derived table with an older vintage. The CLI reads the official INSEE
archive and the commune file directly, and prints one row. Raw transcript:
[`benchmarks/mcp-vs-cli.json`](benchmarks/mcp-vs-cli.json).

## Why it stays small

The same search, measured with `o200k_base`:

| What the model reads | Tokens |
|---|---|
| Raw `data.gouv.fr` API JSON, 3 datasets | 22,187 |
| `data-gouv-cli search-datasets`, 3 datasets | **522** |

42× less context for the same three datasets, before the model reads a single
row. The CLI projects the seven fields an agent actually uses, prints them as
TOON, and exits.

<details>
<summary>How the tokens were counted</summary>

```bash
curl -s "https://www.data.gouv.fr/api/1/datasets/?q=zonage%20ABC&page_size=3" > raw.json
data-gouv-cli search-datasets "zonage ABC" --page-size 3 > cli.txt
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
uv tool install "git+https://github.com/aiandcivilization/data-gouv-cli.git"
```

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 to 3.15.

<details>
<summary>Other ways to install</summary>

```bash
# pipx
pipx install "git+https://github.com/aiandcivilization/data-gouv-cli.git"

# run without installing
uvx --from "git+https://github.com/aiandcivilization/data-gouv-cli.git" data-gouv-cli --help

# from source
git clone https://github.com/aiandcivilization/data-gouv-cli.git
cd data-gouv-cli && uv sync && uv run data-gouv-cli --help

# with the remote-ZIP extra
uv tool install "data-gouv-cli[remote] @ git+https://github.com/aiandcivilization/data-gouv-cli.git"
```
</details>

## 30-second tour

Search, then ask for the files:

```bash
data-gouv-cli search-datasets "zonage ABC" --page-size 3
data-gouv-cli dataset-resources 656715871172d08f8f680063
```

Run SQL on a remote CSV — nothing is downloaded:

```bash
data-gouv-cli query \
  "https://static.data.gouv.fr/resources/liste-des-communes-selon-le-zonage-abc/20260703-091314/liste-ensemble-des-communes-zonage-abc-en-vigueur-26-juin-2026.csv" \
  --sql 'SELECT "Zonage ABC en vigueur depuis le 26 juin 2026" AS zone, count(*) AS communes
         FROM data GROUP BY 1 ORDER BY 2 DESC'
```

```text
source: "https://static.data.gouv.fr/resources/liste-des-communes-selon-le-zonage-abc/..."
format: csv
strategy: httpfs_direct
rows_returned: 5
cache_dir: /home/ubuntu/.cache/data-gouv-cli
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
`data-gouv-cli <command> --help` for the flags of one command.

## Recipes

<details>
<summary><b>Find every file of a dataset</b></summary>

```bash
data-gouv-cli resolve 6564969d3579e21795ebd378
```

Returns the dataset metadata and a table of resources: id, title, format, size,
URL, and whether the tabular API can serve it.
</details>

<details>
<summary><b>Query a remote ZIP member</b></summary>

```bash
data-gouv-cli query \
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
data-gouv-cli download-resource <resource-id> --format csv --dest ./data
data-gouv-cli query ./data/<downloaded>.csv --sql "SELECT * FROM data LIMIT 5"
```
</details>

<details>
<summary><b>Call any JSON API</b></summary>

```bash
data-gouv-cli api "https://www.data.gouv.fr/api/1/datasets/?q=eau&page_size=2"
```

The payload is printed as TOON, so pagination and nested objects stay readable
in a terminal.
</details>

<details>
<summary><b>Download a resource for offline work</b></summary>

```bash
data-gouv-cli download-resource <resource-id> --dest ./data
```

`--dest` defaults to `./downloads` in the current directory.
</details>

<details>
<summary><b>Check how a dataset is used</b></summary>

```bash
data-gouv-cli metrics datasets 6564969d3579e21795ebd378 --limit 2
```

`dataservice-openapi` only answers for the catalogued APIs that publish an
`openapi_url`. When none exists it prints `note: No OpenAPI spec URL available.`
</details>

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATA_GOUV_CACHE` | `~/.cache/data-gouv-cli` | Where downloaded files and remote reads are cached. |
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
