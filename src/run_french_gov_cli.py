from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, NoReturn, Optional

import typer
from _vendor.cli_common.toon_help import install_toon_help_patch
from _vendor.cli_common.toon_output import render_data_as_toon
from rich.console import Console
from toon import encode as toon_encode

from french_gov_logic import FrenchGovTool

install_toon_help_patch(
    "french-gov-cli",
    "French Government Data CLI — data.gouv.fr catalogue, remote SQL queries, generic JSON APIs",
)

app = typer.Typer(
    name="french-gov-cli",
    help=(
        "French Government Data CLI — data.gouv.fr catalogue, remote SQL queries, generic JSON APIs.\n\n"
        "Catalogue : datasets, resources, dataservices, organizations, metrics.\n"
        "Query     : run SQL over a remote csv/parquet/json/zip without downloading it.\n"
        "API       : call any JSON API and get the answer as TOON.\n\n"
        "TOON output only. Set DATAGOUV_API_ENV=demo for the demo environment."
    ),
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)
tool = FrenchGovTool()

DS_COLS = ["id", "title", "organization", "tags", "resources_count", "first_resource_url", "url"]
DSV_COLS = ["id", "title", "organization", "base_api_url", "openapi_url", "tags", "url"]
ORG_COLS = ["id", "name", "acronym", "badge", "datasets", "url"]
RES_COLS = ["id", "title", "format", "mime", "type", "size", "content_length", "url", "tabular"]
EP_COLS = ["method", "path", "summary"]


def _emit_list(rows: list[dict], cols: list[str]) -> None:
    """Print a table as TOON."""
    console.print(render_data_as_toon(cols, rows))


def _emit_obj(obj: dict) -> None:
    """Print an object as TOON."""
    console.print(toon_encode(obj))


def _fail(message: str | Exception, code: int = 1) -> NoReturn:
    """Print one error line and stop.

    The body of a failed API call is printed verbatim, so it is escaped: a raw
    ``[...]`` in the payload would otherwise be parsed as Rich markup and blow
    up the error path itself.
    """
    from rich.markup import escape

    err_console.print(f"[red]Error:[/red] {escape(str(message))}")
    raise typer.Exit(code)


def _scalarize(rows: list[dict]) -> list[dict]:
    """Turn nested objects into compact JSON so every cell stays a scalar."""
    import json as _json

    return [
        {
            k: (_json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
            for k, v in row.items()
        }
        for row in rows
    ]


def _kv(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop the keys that carry no information."""
    return {k: v for k, v in mapping.items() if v is not None}


def _parse_pairs(pairs: list[str], flag: str) -> dict[str, str]:
    """Parse repeated ``key=value`` options."""
    out: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise typer.BadParameter(f"{flag} expects key=value, got {item!r}")
        key, value = item.split("=", 1)
        out[key.strip()] = value
    return out


@app.command("search-datasets")
def search_datasets(
    query: Annotated[str, typer.Argument(help="Keywords to search datasets")],
    page: Annotated[int, typer.Option("--page", "-p", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Page size (max 100)")] = 20,
) -> None:
    """Search datasets on data.gouv.fr (resource URLs included)."""
    try:
        _emit_list(tool.search_datasets(query, page=page, page_size=page_size), DS_COLS)
    except Exception as e:
        _fail(e)


@app.command("dataset")
def dataset(
    dataset_id: Annotated[str, typer.Argument(help="Dataset ID or slug")],
) -> None:
    """Get detailed info about a dataset."""
    try:
        _emit_obj(tool.get_dataset(dataset_id))
    except Exception as e:
        _fail(e)


@app.command("resolve")
def resolve(
    dataset_id: Annotated[str, typer.Argument(help="Dataset ID or slug")],
) -> None:
    """Resolve a dataset into ready-to-use file URLs (one call)."""
    try:
        obj = tool.resolve_dataset(dataset_id)
    except Exception as e:
        _fail(e)
    resources = obj.get("resources") or []
    meta = _kv(
        {
            "id": obj.get("id"),
            "title": obj.get("title"),
            "organization": obj.get("organization"),
            "license": obj.get("license"),
            "last_modified": obj.get("last_modified"),
            "resources_count": len(resources),
            "url": obj.get("url"),
        }
    )
    console.print(toon_encode(meta))
    if resources:
        console.print(render_data_as_toon(RES_COLS, _scalarize(resources)))


@app.command("dataset-resources")
def dataset_resources(
    dataset_id: Annotated[str, typer.Argument(help="Dataset ID")],
) -> None:
    """List the resources of a dataset with their download URLs."""
    try:
        _emit_list(tool.list_dataset_resources(dataset_id), RES_COLS)
    except Exception as e:
        _fail(e)


@app.command("resource")
def resource(
    resource_id: Annotated[str, typer.Argument(help="Resource ID")],
) -> None:
    """Get detailed info about a resource."""
    try:
        _emit_obj(tool.get_resource_info(resource_id))
    except Exception as e:
        _fail(e)


@app.command("query")
def query(
    source: Annotated[
        str,
        typer.Argument(help="URL, local path, or resource:<id> of the tabular file"),
    ],
    sql: Annotated[
        Optional[str],
        typer.Option("--sql", "-q", help="SQL executed against the view `data`"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows returned")] = 50,
    delim: Annotated[Optional[str], typer.Option("--delim", help="CSV delimiter (default: auto)")] = None,
    member: Annotated[
        Optional[str], typer.Option("--member", help="Archive member to read when the source is a zip")
    ] = None,
    cache_dir: Annotated[Optional[str], typer.Option("--cache", help="Cache directory")] = None,
) -> None:
    """Run SQL over a remote or local tabular file without downloading it."""
    try:
        result = tool.query_source(
            source, sql=sql, limit=limit, delim=delim, member=member, cache_dir=cache_dir
        )
    except Exception as e:
        _fail(e)
    meta = _kv(
        {
            "source": result["source"],
            "format": result["format"],
            "strategy": result["strategy"],
            "rows_returned": result["rows_returned"],
            "cache_dir": result["cache_dir"],
        }
    )
    console.print(toon_encode(meta))
    cols = result["columns"]
    rows = result["rows"]
    if cols and rows:
        console.print(render_data_as_toon(cols, rows))
    elif not rows:
        console.print(toon_encode({"note": "query returned no row"}))


@app.command("api")
def api(
    url: Annotated[str, typer.Argument(help="API URL to call")],
    method: Annotated[str, typer.Option("--method", "-X", help="HTTP method")] = "GET",
    params: Annotated[
        Optional[list[str]], typer.Option("--param", "-p", help="Query parameter key=value (repeatable)")
    ] = None,
    headers: Annotated[
        Optional[list[str]], typer.Option("--header", "-H", help="Request header key=value (repeatable)")
    ] = None,
    body: Annotated[Optional[str], typer.Option("--body", help="JSON request body")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows returned")] = 50,
    field: Annotated[Optional[str], typer.Option("--field", help="Dot path of the field to extract")] = None,
) -> None:
    """Call any JSON API and get the answer as TOON."""
    import json as _json

    parsed_body = None
    if body:
        try:
            parsed_body = _json.loads(body)
        except ValueError as e:
            _fail(f"--body is not valid JSON: {e}")
    try:
        payload = tool.api_request(
            url,
            method=method,
            params=_parse_pairs(params or [], "--param"),
            headers=_parse_pairs(headers or [], "--header"),
            body=parsed_body,
        )
    except Exception as e:
        _fail(e)

    if field:
        node: Any = payload
        for part in field.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            elif isinstance(node, list) and node and isinstance(node[0], dict):
                node = [row.get(part) for row in node]
            else:
                node = None
            if node is None:
                break
        payload = node

    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        rows = payload[:limit] if limit and limit > 0 else payload
        cols = list(rows[0].keys())
        console.print(render_data_as_toon(cols, rows))
    elif isinstance(payload, dict):
        inner = payload.get("data")
        if isinstance(inner, list) and inner and all(isinstance(x, dict) for x in inner):
            rows = inner[:limit] if limit and limit > 0 else inner
            meta = {k: v for k, v in payload.items() if k != "data" and not isinstance(v, (list, dict))}
            console.print(toon_encode(meta))
            console.print(render_data_as_toon(list(rows[0].keys()), _scalarize(rows)))
        else:
            console.print(toon_encode(payload))
    else:
        console.print(toon_encode({"value": payload}))


@app.command("query-resource")
def query_resource(
    resource_id: Annotated[str, typer.Argument(help="Resource ID")],
    page: Annotated[int, typer.Option("--page", "-p", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Page size")] = 20,
) -> None:
    """Query rows of a resource through the tabular API."""
    try:
        data = tool.query_resource_data(resource_id, page=page, page_size=page_size)
    except Exception as e:
        _fail(e)
    raw_cols = data.get("columns") or []
    cols = [c.get("name") if isinstance(c, dict) else c for c in raw_cols]
    rows = data.get("data", [])
    if not cols and rows:
        cols = list(rows[0].keys())
    if cols and rows:
        console.print(render_data_as_toon(cols, rows))
    else:
        console.print(toon_encode(data))


@app.command("search-dataservices")
def search_dataservices(
    query: Annotated[str, typer.Argument(help="Keywords to search third-party APIs")],
    page: Annotated[int, typer.Option("--page", "-p", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Page size")] = 20,
) -> None:
    """Search the third-party APIs cataloged on data.gouv.fr."""
    try:
        _emit_list(tool.search_dataservices(query, page=page, page_size=page_size), DSV_COLS)
    except Exception as e:
        _fail(e)


@app.command("dataservice")
def dataservice(
    dataservice_id: Annotated[str, typer.Argument(help="Dataservice ID")],
) -> None:
    """Get detailed info about a third-party API."""
    try:
        _emit_obj(tool.get_dataservice(dataservice_id))
    except Exception as e:
        _fail(e)


@app.command("dataservice-openapi")
def dataservice_openapi(
    dataservice_id: Annotated[str, typer.Argument(help="Dataservice ID")],
) -> None:
    """Fetch and summarize the OpenAPI spec of a third-party API."""
    try:
        obj = tool.get_dataservice_openapi(dataservice_id)
    except Exception as e:
        _fail(e)
    meta = {k: v for k, v in obj.items() if k != "endpoints"}
    console.print(toon_encode(meta))
    eps = obj.get("endpoints", [])
    if eps:
        console.print(render_data_as_toon(EP_COLS, eps))


@app.command("search-orgs")
def search_orgs(
    query: Annotated[str, typer.Argument(help="Keywords (optional)")] = "",
    page: Annotated[int, typer.Option("--page", "-p", help="Page number")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", "-n", help="Page size")] = 20,
    sort: Annotated[Optional[str], typer.Option("--sort", help="Sort field (e.g. datasets, -datasets)")] = None,
    badge: Annotated[Optional[str], typer.Option("--badge", help="Badge filter")] = None,
) -> None:
    """Search the publishing organizations."""
    try:
        rows = tool.search_organizations(query=query, page=page, page_size=page_size, sort=sort, badge=badge)
        _emit_list(rows, ORG_COLS)
    except Exception as e:
        _fail(e)


@app.command("org")
def org(
    org_id: Annotated[str, typer.Argument(help="Organization ID or slug")],
) -> None:
    """Get detailed info about an organization."""
    try:
        _emit_obj(tool.get_organization(org_id))
    except Exception as e:
        _fail(e)


@app.command("download-resource")
def download_resource(
    resource_id: Annotated[str, typer.Argument(help="Resource ID")],
    dest: Annotated[str, typer.Option("--dest", "-d", help="Destination directory")] = "/tmp/opencode",
    fmt: Annotated[str, typer.Option("--format", "-f", help="Target format: auto|csv|parquet|original")] = "auto",
) -> None:
    """Download a resource (streamed, max speed) with optional auto-conversion."""
    try:
        _emit_obj(tool.download_resource(resource_id, dest_dir=dest, fmt=fmt))
    except Exception as e:
        _fail(e, code=2)


@app.command("metrics")
def metrics(
    model: Annotated[str, typer.Argument(help="Metrics model (datasets, resources, organizations, reuses, site)")],
    id_value: Annotated[str, typer.Argument(help="ID to filter by")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max records")] = 12,
    sort: Annotated[str, typer.Option("--sort", help="Sort order (asc/desc)")] = "desc",
) -> None:
    """Get usage metrics for a dataset/resource/org."""
    try:
        rows = tool.get_metrics(model, id_value, limit=limit, sort_order=sort)
    except Exception as e:
        _fail(e)
    if rows:
        console.print(render_data_as_toon(list(rows[0].keys()), rows))
    else:
        console.print(toon_encode({"metrics": 0}))


@app.command("inspect")
def inspect() -> None:
    """Show the tool's own metadata (package, entrypoint, skill, index)."""
    from _vendor.cli_common import build_inspect_meta

    tool_dir = Path(__file__).resolve().parent
    meta = build_inspect_meta(
        "french-gov-cli",
        tool_dir,
        "command-line-tools/subskills/french-gov-cli",
        entrypoint="run_french_gov_cli.py",
    )
    meta["version"] = _version(tool_dir)
    console.print(toon_encode(meta))


def _version(tool_dir: Path) -> str:
    """Read the package version from pyproject.toml."""
    try:
        for line in (tool_dir / "pyproject.toml").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def main() -> None:
    app()


if __name__ == "__main__":
    app()
