"""French government open data logic — data.gouv.fr APIs, generic HTTP APIs, remote tabular queries.

Three capabilities, one tool:

* catalogue  : datasets, resources, dataservices, organizations, metrics (data.gouv.fr)
* query      : run SQL over a remote or local tabular file without downloading it
* api        : call any JSON API and get the answer as TOON

The query layer exists because the data.gouv catalogue is mostly *large* remote
tabular files (a 1.86 GB parquet, a 5.3 MB zip that unpacks to 58 MB of CSV).
Downloading them to look at five rows is the wrong default.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

USER_AGENT = "french-gov-cli/0.2.0"
DEFAULT_TIMEOUT = 60.0
CACHE_DIR = Path(os.getenv("FRENCH_GOV_CACHE", Path.home() / ".cache" / "french-gov-cli"))


def _env() -> str:
    return os.getenv("DATAGOUV_API_ENV", "prod").strip().lower() or "prod"


def base_url(api_name: str) -> str:
    env = _env()
    targets = {
        "demo": {
            "datagouv_api": "https://demo.data.gouv.fr/api/",
            "tabular_api": "https://tabular-api.preprod.data.gouv.fr/api/",
            "metrics_api": "https://metric-api.data.gouv.fr/api/",
        },
        "prod": {
            "datagouv_api": "https://www.data.gouv.fr/api/",
            "tabular_api": "https://tabular-api.data.gouv.fr/api/",
            "metrics_api": "https://metric-api.data.gouv.fr/api/",
        },
    }
    if env not in targets:
        env = "prod"
    return targets[env][api_name]


def _get(url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _site_url(path: str) -> str:
    env = _env()
    site = "https://demo.data.gouv.fr/" if env == "demo" else "https://www.data.gouv.fr/"
    return site.rstrip("/") + "/" + path.lstrip("/")


# --------------------------------------------------------------------------- #
# format detection
# --------------------------------------------------------------------------- #

_CSV_EXTS = (".csv", ".tsv", ".txt", ".tab")
_PARQUET_EXTS = (".parquet", ".pq", ".parq")
_JSON_EXTS = (".json", ".jsonl", ".ndjson", ".geojson")
_ZIP_EXTS = (".zip",)
_EXCEL_EXTS = (".xlsx", ".xls")


def detect_format(location: str, content_type: str | None = None, magic: bytes = b"") -> str:
    """Return one of: zip, parquet, json, csv, excel, html, unknown.

    The extension is a hint, not a truth: data.gouv URLs often carry no
    extension at all (``.../DS_FILOSOFI_CC_2023_CSV_FR``), so the magic bytes
    decide when they are available.
    """
    path = location.split("?")[0].split("#")[0]
    ext = Path(path).suffix.lower()
    if ext in _ZIP_EXTS:
        return "zip"
    if ext in _PARQUET_EXTS:
        return "parquet"
    if ext in _JSON_EXTS:
        return "json"
    if ext in _CSV_EXTS:
        return "csv"
    if ext in _EXCEL_EXTS:
        return "excel"

    head = magic[:16]
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if head.startswith(b"PAR1"):
        return "parquet"
    lowered = magic[:512].lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html")):
        return "html"
    if lowered[:1] in (b"{", b"["):
        return "json"

    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if "zip" in ct:
            return "zip"
        if "parquet" in ct:
            return "parquet"
        if "json" in ct:
            return "json"
        if "html" in ct:
            return "html"
        if "csv" in ct or "text/plain" in ct:
            return "csv"
    return "unknown"


def _head_bytes(url: str, size: int = 16) -> tuple[bytes, str | None]:
    """Return the first bytes and the content-type of a remote file.

    Uses a ranged GET when the server honours Range; otherwise it reads the
    first bytes of a streamed body and closes it, so nothing is transferred.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{size - 1}"},
            stream=True,
            timeout=20,
        )
        ctype = resp.headers.get("Content-Type")
        if resp.status_code == 206:
            data = resp.raw.read(size, decode_content=True) or b""
        else:
            data = resp.raw.read(size, decode_content=True) or b""
        resp.close()
        return data, ctype
    except requests.RequestException:
        return b"", None


def _supports_range(url: str) -> bool:
    """True when the server answers a ranged GET with 206."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1"},
            stream=True,
            timeout=15,
        )
        code = resp.status_code
        resp.close()
        return code == 206
    except requests.RequestException:
        return False


# --------------------------------------------------------------------------- #
# zip handling
# --------------------------------------------------------------------------- #


def _zip_member_score(name: str, size: int) -> tuple[int, int]:
    """Rank an archive member: a data file first, then the biggest one."""
    lower = name.lower()
    if lower.endswith((".csv", ".parquet", ".json", ".jsonl", ".ndjson")):
        tier = 0 if "data" in lower else 1
    elif lower.endswith((".shp", ".gpkg", ".dbf", ".prj", ".cpg")):
        tier = 3
    elif lower.endswith((".pdf", ".txt", ".xml", ".html")):
        tier = 4
    else:
        tier = 2
    return (tier, size)


def _pick_member(members: list[zipfile.ZipInfo], wanted: str | None = None) -> str:
    """Choose the archive member to read: explicit match, else the best data file.

    "Best" means a data file whose name says so, and among those the biggest
    one: the metadata companion of a data file is always smaller, so size
    separates them.
    """
    if wanted:
        for info in members:
            if info.filename == wanted or Path(info.filename).name == wanted:
                return info.filename
        available = ", ".join(i.filename for i in members)
        raise ValueError(f"member {wanted!r} not in archive; available: {available}")
    candidates = [info for info in members if not info.filename.endswith("/")]
    if not candidates:
        raise ValueError("archive is empty")
    best = min(
        candidates,
        key=lambda info: (_zip_member_score(info.filename, info.file_size)[0], -info.file_size),
    )
    return best.filename


def _extract_local_member(archive_path: Path, member: str, dest_dir: Path) -> Path:
    """Extract one member of a local zip into the cache and return its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{Path(archive_path).stem}__{Path(member).name}"
    with zipfile.ZipFile(archive_path) as zf, zf.open(member) as src, out.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return out


def _supports_suffix_range(url: str) -> bool:
    """True when the server answers a *suffix* range request with 206.

    A suffix range (``Range: bytes=-1024``) is what a remote zip reader needs:
    it fetches the central directory from the end of the archive without
    downloading it. Some servers accept prefix ranges but reject suffix ones
    with a 500 (api.insee.fr does), so the capability is probed, never assumed.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Range": "bytes=-1024"},
            stream=True,
            timeout=15,
        )
        code = resp.status_code
        resp.close()
        return code == 206
    except requests.RequestException:
        return False


def _extract_remote_member(
    url: str, member: str, dest_dir: Path
) -> Path:
    """Extract one member of a remote zip over HTTP range requests.

    ``remotezip`` is optional: it is imported lazily so the tool still works
    (via a full download) when the extra is not installed.
    """
    try:
        import remotezip  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "remotezip is not installed (needed to read a zip member over HTTP range "
            "requests). Install it with: cd ~/.god-tier-cli/tools/french_gov_tool && "
            "uv sync --extra remote"
        ) from exc

    last_error = ""
    if not _supports_suffix_range(url):
        raise RuntimeError(
            "the server does not answer suffix range requests (bytes=-N); "
            "a remote zip can only be read with full-range support"
        )
    try:
        with remotezip.RemoteZip(url, timeout=DEFAULT_TIMEOUT, support_suffix_range=True) as zf:
            target = _pick_member(zf.infolist(), member)
            dest_dir.mkdir(parents=True, exist_ok=True)
            out = dest_dir / f"{Path(url).name}__{Path(target).name}"
            with zf.open(target) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            return out
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
    raise RuntimeError(f"remote zip read failed ({last_error})")


# --------------------------------------------------------------------------- #
# duckdb query engine
# --------------------------------------------------------------------------- #


def _duckdb():
    """Open a DuckDB connection with the httpfs extension when available."""
    import duckdb

    con = duckdb.connect()
    for stmt in ("LOAD httpfs", "INSTALL httpfs; LOAD httpfs"):
        try:
            con.execute(stmt)
            break
        except Exception:
            continue
    return con


def _read_expr(path: str, fmt: str, delim: str | None) -> str:
    """Return the DuckDB table function for a given format."""
    lit = path.replace("'", "''")
    if fmt == "parquet":
        return f"read_parquet('{lit}')"
    if fmt == "json":
        return f"read_json_auto('{lit}')"
    if fmt == "csv":
        options = ["header=true", "ignore_errors=true", "sample_size=-1"]
        if delim:
            options.append(f"delim='{delim}'")
        return f"read_csv_auto('{lit}', {', '.join(options)})"
    raise ValueError(f"format {fmt!r} is not queryable by DuckDB")


def _run_sql(con, sql: str) -> tuple[list[str], list[dict]]:
    """Execute SQL and return (column names, rows as dicts)."""
    cur = con.execute(sql)
    cols = [d[0] for d in (cur.description or [])]
    rows = [dict(zip(cols, values, strict=False)) for values in cur.fetchall()]
    return cols, rows


def _has_limit(sql: str) -> bool:
    return "limit" in sql.lower().rsplit("select", 1)[-1]


class FrenchGovTool:
    # ------------------------------------------------------------------ #
    # catalogue
    # ------------------------------------------------------------------ #

    def search_datasets(self, query: str, page: int = 1, page_size: int = 20) -> list[dict]:
        """Search datasets on data.gouv.fr.

        Two endpoints are combined on purpose:

        * **v2** gives the recall (it matches loosely), but it truncates the
          resources, so the file URL is missing;
        * **v1** returns the full resource list with the download URLs, but it
          ANDs the keywords and misses datasets whose text does not contain
          every word.

        So v2 selects, and v1 hydrates the winners in parallel to recover the
        first resource URL.
        """
        url = base_url("datagouv_api") + "2/datasets/search/"
        data = _get(url, params={"q": query, "page": page, "page_size": page_size})
        results = data.get("data", data.get("results", []))
        rows = []
        for ds in results or []:
            org = ds.get("organization")
            rows.append(
                {
                    "id": ds.get("id"),
                    "slug": ds.get("slug"),
                    "title": ds.get("title") or ds.get("name"),
                    "organization": org.get("name") if isinstance(org, dict) else org,
                    "tags": ds.get("tags") or [],
                    "resources_count": None,
                    "first_resource_url": None,
                    "url": _site_url(f"datasets/{ds.get('slug') or ds.get('id')}"),
                }
            )
        self._hydrate_resource_urls(rows)
        return rows

    def _hydrate_resource_urls(self, rows: list[dict]) -> None:
        """Fill ``resources_count`` and ``first_resource_url`` from the v1 API."""
        from concurrent.futures import ThreadPoolExecutor

        ids = [r["id"] for r in rows if r.get("id")]
        if not ids:
            return

        def _one(dataset_id: str) -> tuple[str, int | None, str | None]:
            try:
                detail = self.get_dataset(dataset_id)
            except Exception:
                return dataset_id, None, None
            resources = detail.get("resources") or []
            first = next((res.get("url") for res in resources if res.get("url")), None)
            return dataset_id, len(resources) or None, first

        with ThreadPoolExecutor(max_workers=8) as pool:
            for dataset_id, count, first_url in pool.map(_one, ids):
                for row in rows:
                    if row.get("id") == dataset_id:
                        if count is not None:
                            row["resources_count"] = count
                        if first_url:
                            row["first_resource_url"] = first_url
                        break

    def get_dataset(self, dataset_id: str) -> dict:
        """Return a dataset with its full resource list (URLs included)."""
        url = base_url("datagouv_api") + f"1/datasets/{dataset_id}/"
        data = _get(url)
        org = data.get("organization")
        org_name = org.get("name") if isinstance(org, dict) else org
        return {
            "id": data.get("id"),
            "slug": data.get("slug"),
            "title": data.get("title") or data.get("name"),
            "description": data.get("description"),
            "description_short": data.get("description_short"),
            "organization": org_name,
            "tags": data.get("tags", []),
            "license": data.get("license"),
            "created_at": data.get("created_at"),
            "last_modified": data.get("last_modified") or data.get("last_update"),
            "resources": [self._normalize_resource(r) for r in (data.get("resources") or [])],
            "url": _site_url(f"datasets/{data.get('slug') or data.get('id')}"),
        }

    @staticmethod
    def _normalize_resource(res: dict) -> dict:
        """Normalize one resource, keeping the URL and the size metadata.

        ``extras.analysis:content-length`` carries the real file size, known
        without downloading a byte.
        """
        raw_extras = res.get("extras")
        extras: dict[str, Any] = raw_extras if isinstance(raw_extras, dict) else {}
        content_length = extras.get("analysis:content-length")
        checksum = extras.get("analysis:checksum")
        return {
            "id": res.get("id"),
            "title": res.get("title") or res.get("name"),
            "format": res.get("format"),
            "mime": res.get("mime"),
            "type": res.get("type"),
            "size": res.get("filesize") or res.get("size"),
            "content_length": content_length,
            "checksum": checksum,
            "url": res.get("url"),
            "dataset_id": res.get("dataset_id"),
            "tabular_available": extras.get("tabular_api"),
        }

    def list_dataset_resources(self, dataset_id: str) -> list[dict]:
        """List the resources of a dataset, with their download URLs."""
        return self.get_dataset(dataset_id).get("resources", [])

    def get_resource_info(self, resource_id: str) -> dict:
        """Return the full description of one resource."""
        url = base_url("datagouv_api") + f"2/datasets/resources/{resource_id}/"
        try:
            data = _get(url)
        except requests.HTTPError:
            url = base_url("datagouv_api") + f"1/datasets/resources/{resource_id}/"
            data = _get(url)
        if isinstance(data, dict) and isinstance(data.get("resource"), dict):
            data = data["resource"]
        return self._normalize_resource(data)

    def tabular_available(self, resource_id: str) -> bool:
        """True when the tabular API can serve rows for this resource.

        Most resources are not indexed (parquet files, Insee archives), so the
        capability is probed, never assumed.
        """
        url = base_url("tabular_api") + f"resources/{resource_id}/data/"
        try:
            resp = requests.get(
                url,
                params={"page_size": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def resolve_dataset(self, dataset_id: str) -> dict:
        """One call that resolves a dataset into ready-to-use file URLs.

        This replaces the three-call chain ``dataset`` -> ``dataset-resources``
        -> ``resource`` (one call per file) that the catalogue used to force.
        """
        ds = self.get_dataset(dataset_id)
        resources = []
        for res in ds.get("resources", []):
            entry = dict(res)
            candidate = (res.get("format") or res.get("mime") or "").lower()
            if "csv" in candidate or "json" in candidate or "json" in (res.get("title") or "").lower():
                entry["tabular"] = self.tabular_available(res.get("id")) if res.get("id") else False
            else:
                entry["tabular"] = None
            resources.append(entry)
        ds["resources"] = resources
        return ds

    def query_resource_data(self, resource_id: str, page: int = 1, page_size: int = 20) -> dict:
        """Query rows of a resource through the tabular API."""
        url = base_url("tabular_api") + f"resources/{resource_id}/data/"
        params = {"page": max(page, 1), "page_size": max(page_size, 1)}
        return _get(url, params=params)

    # ------------------------------------------------------------------ #
    # dataservices, organizations, metrics
    # ------------------------------------------------------------------ #

    def search_dataservices(self, query: str, page: int = 1, page_size: int = 20) -> list[dict]:
        """Search the third-party APIs cataloged on data.gouv.fr."""
        url = base_url("datagouv_api") + "2/dataservices/search/"
        data = _get(url, params={"q": query, "page": page, "page_size": page_size})
        results = data.get("data", data.get("results", []))
        out = []
        for ds in results or []:
            org = ds.get("organization")
            out.append(
                {
                    "id": ds.get("id"),
                    "title": ds.get("title") or ds.get("name"),
                    "organization": org.get("name") if isinstance(org, dict) else org,
                    "base_api_url": ds.get("base_api_url"),
                    "openapi_url": ds.get("openapi_url") or ds.get("doc_tech_link"),
                    "tags": ds.get("tags", []),
                    "url": _site_url(f"dataservices/{ds.get('id')}"),
                }
            )
        return out

    def get_dataservice(self, dataservice_id: str) -> dict:
        """Return one third-party API description."""
        url = base_url("datagouv_api") + f"1/dataservices/{dataservice_id}/"
        data = _get(url)
        org = data.get("organization")
        org_name = org.get("name") if isinstance(org, dict) else org
        return {
            "id": data.get("id"),
            "title": data.get("title") or data.get("name"),
            "description": data.get("description"),
            "organization": org_name,
            "base_api_url": data.get("base_api_url"),
            "openapi_url": data.get("openapi_url") or data.get("doc_tech_link"),
            "license": data.get("license"),
            "created_at": data.get("created_at"),
            "last_modified": data.get("last_modified"),
            "tags": data.get("tags", []),
            "related_datasets": [d.get("id") if isinstance(d, dict) else d for d in data.get("datasets", [])],
            "url": _site_url(f"dataservices/{data.get('id')}"),
        }

    def get_dataservice_openapi(self, dataservice_id: str) -> dict:
        """Fetch and summarize the OpenAPI spec of a third-party API."""
        info = self.get_dataservice(dataservice_id)
        spec_url = info.get("openapi_url")
        if not spec_url:
            return {
                "dataservice_id": dataservice_id,
                "spec_url": None,
                "endpoints": [],
                "note": "No OpenAPI spec URL available.",
            }
        try:
            spec = requests.get(spec_url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT).json()
        except Exception as exc:
            return {"dataservice_id": dataservice_id, "spec_url": spec_url, "endpoints": [], "error": str(exc)}
        endpoints = []
        paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                endpoints.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "summary": (op or {}).get("summary") or (op or {}).get("description", "")[:120],
                    }
                )
        return {
            "dataservice_id": dataservice_id,
            "spec_url": spec_url,
            "base_api_url": info.get("base_api_url"),
            "endpoints": endpoints,
        }

    def search_organizations(
        self,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        badge: str | None = None,
    ) -> list[dict]:
        """Search the publishing organizations."""
        url = base_url("datagouv_api") + "2/organizations/search/"
        params = {"page": page, "page_size": page_size}
        if query:
            params["q"] = query
        if sort:
            params["sort"] = sort
        if badge:
            params["badge"] = badge
        data = _get(url, params=params)
        results = data.get("data", data.get("results", []))
        return [
            {
                "id": org.get("id"),
                "slug": org.get("slug"),
                "name": org.get("name"),
                "acronym": org.get("acronym"),
                "badge": org.get("badge"),
                "datasets": org.get("metrics", {}).get("datasets")
                if isinstance(org.get("metrics"), dict)
                else org.get("datasets"),
                "url": _site_url(f"organizations/{org.get('slug') or org.get('id')}"),
            }
            for org in results or []
        ]

    def get_organization(self, org_id: str) -> dict:
        """Return one publishing organization."""
        url = base_url("datagouv_api") + f"1/organizations/{org_id}/"
        data = _get(url)
        return {
            "id": data.get("id"),
            "slug": data.get("slug"),
            "name": data.get("name"),
            "acronym": data.get("acronym"),
            "description": data.get("description"),
            "badge": data.get("badge"),
            "created_at": data.get("created_at"),
            "url": _site_url(f"organizations/{data.get('slug') or data.get('id')}"),
        }

    def get_metrics(self, model: str, id_value: str, limit: int = 12, sort_order: str = "desc") -> list[dict]:
        """Return the usage metrics of a dataset, resource or organization."""
        id_field = (model.removesuffix("s")) + "_id"
        url = base_url("metrics_api") + f"{model}/data/"
        params = {
            f"{id_field}__exact": id_value,
            "metric_month__sort": sort_order,
            "page_size": str(max(1, min(limit, 50))),
        }
        data = _get(url, params=params)
        return data.get("data", [])

    # ------------------------------------------------------------------ #
    # generic API call
    # ------------------------------------------------------------------ #

    def api_request(
        self,
        url: str,
        method: str = "GET",
        params: dict | None = None,
        headers: dict | None = None,
        body: Any = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        """Call any JSON API and return the decoded payload.

        The full error body is raised on failure: a sliced error message
        hides the field that actually went wrong.
        """
        hdrs = {"User-Agent": USER_AGENT}
        hdrs.update(headers or {})
        try:
            resp = requests.request(
                method.upper(),
                url,
                params=params or None,
                headers=hdrs,
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"{method.upper()} {url} failed: {exc}") from exc
        if not resp.ok:
            raise RuntimeError(
                f"{method.upper()} {url} returned HTTP {resp.status_code}: {resp.text}"
            )
        try:
            return resp.json()
        except ValueError:
            return {"status": resp.status_code, "content_type": resp.headers.get("Content-Type"), "text": resp.text}

    # ------------------------------------------------------------------ #
    # remote query
    # ------------------------------------------------------------------ #

    def query_source(
        self,
        source: str,
        sql: str | None = None,
        limit: int = 50,
        delim: str | None = None,
        member: str | None = None,
        cache_dir: str | None = None,
    ) -> dict:
        """Run SQL over a remote or local tabular file.

        The source is a URL, a local path, or ``resource:<id>``. The SQL runs
        against a view named ``data``.

        Strategy, in order of preference:

        1. local file -> DuckDB reads it directly;
        2. remote csv/parquet/json -> DuckDB httpfs reads it over HTTP range
           requests, nothing is downloaded;
        3. remote zip -> the member is fetched over HTTP range requests
           (``remotezip``) or the archive is downloaded and unpacked locally;
        4. any remote read that fails -> the file is downloaded into the cache
           and read locally. Every fallback prints one stderr line.
        """
        cache = Path(cache_dir) if cache_dir else CACHE_DIR
        cache.mkdir(parents=True, exist_ok=True)

        location, meta = self._resolve_source(source)
        is_remote = location.startswith(("http://", "https://"))

        fmt = meta.get("format") or "unknown"
        if fmt in ("unknown", "html"):
            magic, ctype = _head_bytes(location, 16) if is_remote else (b"", None)
            fmt = detect_format(location, ctype or meta.get("content_type"), magic)
        if fmt == "excel":
            resource_id = meta.get("resource_id") or "<resource-id>"
            raise RuntimeError(
                "Excel files cannot be queried in place. Convert the resource to CSV, "
                "then query the local file: "
                f"french-gov-cli download-resource {resource_id} --format csv --dest . "
                "&& french-gov-cli query <downloaded.csv> --sql \"SELECT * FROM data LIMIT 5\""
            )

        strategy = ""
        path_for_read = location
        fallback_notes: list[str] = []

        if is_remote and fmt == "zip":
            path_for_read, strategy, fmt = self._prepare_zip_member(location, member, cache, meta)
        elif is_remote:
            path_for_read, strategy = self._prepare_remote_tabular(location, fmt, cache, meta)

        con = _duckdb()
        try:
            expr = _read_expr(path_for_read, fmt, delim)
            con.execute(f"CREATE OR REPLACE VIEW data AS SELECT * FROM {expr}")
            final_sql = sql or "SELECT * FROM data"
            if limit and limit > 0 and not _has_limit(final_sql):
                final_sql = f"SELECT * FROM ({final_sql}) LIMIT {int(limit)}"
            cols, rows = _run_sql(con, final_sql)
        finally:
            con.close()

        return {
            "source": location,
            "format": fmt,
            "strategy": strategy,
            "sql": final_sql,
            "rows_returned": len(rows),
            "columns": cols,
            "rows": rows,
            "cache_dir": str(cache),
            "notes": fallback_notes,
            "resource_id": meta.get("resource_id"),
        }

    def _resolve_source(self, source: str) -> tuple[str, dict]:
        """Turn a source expression into a concrete location plus metadata."""
        if source.startswith("resource:"):
            rid = source.split(":", 1)[1]
            info = self.get_resource_info(rid)
            url = info.get("url")
            if not url:
                raise RuntimeError(f"resource {rid} has no download URL")
            meta = {
                "format": info.get("format") or info.get("mime"),
                "content_type": info.get("mime"),
                "resource_id": rid,
            }
            return url, meta
        if source.startswith(("http://", "https://")):
            return source, {"format": None, "content_type": None, "resource_id": None}
        path = Path(source).expanduser()
        if not path.exists():
            raise RuntimeError(f"local file not found: {path}")
        return str(path), {"format": None, "content_type": None, "resource_id": None}

    def _prepare_remote_tabular(
        self, url: str, fmt: str, cache: Path, meta: dict
    ) -> tuple[str, str]:
        """Try a remote DuckDB read; fall back to a local download."""
        con = _duckdb()
        try:
            expr = _read_expr(url, fmt, None)
            con.execute(f"CREATE OR REPLACE VIEW probe AS SELECT * FROM {expr} LIMIT 1")
            con.execute("SELECT * FROM probe")
            return url, "httpfs_direct"
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        finally:
            con.close()
        local = self._download_to_cache(url, cache)
        print(
            f"[french-gov-cli] remote read of {url} failed ({reason}); "
            f"downloaded to {local} instead.",
            file=sys.stderr,
        )
        return str(local), "download_local"

    def _prepare_zip_member(
        self, url: str, member: str | None, cache: Path, meta: dict
    ) -> tuple[str, str, str]:
        """Get one member of a remote zip, over HTTP ranges when possible.

        Returns the path of the extracted member, the strategy used and the
        format of the member itself (the archive format is not the format of
        the data inside it).
        """
        try:
            out = _extract_remote_member(url, member or "", cache)
            return str(out), "zip_range", detect_format(str(out))
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        print(
            f"[french-gov-cli] remote zip read of {url} failed ({reason}); "
            "falling back to a full download of the archive.",
            file=sys.stderr,
        )
        archive = self._download_to_cache(url, cache)
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
        target = _pick_member(infos, member)
        out = _extract_local_member(archive, target, cache)
        print(
            f"[french-gov-cli] extracted {target} from {archive} to {out}.",
            file=sys.stderr,
        )
        return str(out), "zip_download", detect_format(str(out))

    def _download_to_cache(self, url: str, cache: Path) -> Path:
        """Download a remote file into the cache and return its path."""
        cache.mkdir(parents=True, exist_ok=True)
        name = url.split("?")[0].rstrip("/").split("/")[-1] or "download"
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        out = cache / safe
        t0 = time.time()
        with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with out.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        elapsed = time.time() - t0
        print(
            f"[french-gov-cli] downloaded {out} ({out.stat().st_size} bytes in {elapsed:.1f}s).",
            file=sys.stderr,
        )
        return out

    # ------------------------------------------------------------------ #
    # download
    # ------------------------------------------------------------------ #

    def download_resource(self, resource_id: str, dest_dir: str = "downloads", fmt: str = "auto") -> dict:
        """Download a resource, with a guard against landing pages.

        A data.gouv resource URL sometimes points to an HTML page (the Insee
        file pages do). Downloading it silently reports success for a file that
        is not data, so the content is sniffed and the caller is told.
        """
        info = self.get_resource_info(resource_id)
        url = info.get("url")
        if not url:
            raise ValueError("No download URL for resource")
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        name = url.split("?")[0].rstrip("/").split("/")[-1] or resource_id
        original_path = str(Path(dest_dir) / name)
        t0 = time.time()
        with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type")
            with Path(original_path).open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        elapsed = time.time() - t0
        size = Path(original_path).stat().st_size
        speed = size / elapsed if elapsed > 0 else 0

        with Path(original_path).open("rb") as f:
            head = f.read(512)
        sniffed = detect_format(original_path, content_type, head)
        if sniffed == "html":
            raise RuntimeError(
                f"{url} returned an HTML page (content-type: {content_type}), not a data file. "
                f"Saved to {original_path}. Exact next command: "
                f"french-gov-cli query \"{url}\" --sql \"select * from data limit 10\""
            )

        src_ext = Path(name).suffix.lower().lstrip(".")
        if fmt == "auto":
            fmt = src_ext or sniffed
        target_path = original_path
        converted = False

        if fmt == "csv" and src_ext in ("xlsx", "xls"):
            csv_path = str(Path(original_path).with_suffix(".csv"))
            _excel_to_csv(original_path, csv_path, src_ext)
            target_path = csv_path
            converted = True
        if fmt == "parquet" and src_ext != "parquet":
            import pyarrow.csv as pcsv
            import pyarrow.parquet as pq

            src_csv = original_path
            if src_ext in ("xlsx", "xls"):
                src_csv = str(Path(original_path).with_suffix(".csv"))
                _excel_to_csv(original_path, src_csv, src_ext)
            parquet_path = str(Path(original_path).with_suffix(".parquet"))
            pq.write_table(pcsv.read_csv(src_csv), parquet_path)
            target_path = parquet_path
            converted = True

        return {
            "resource_id": resource_id,
            "original_file": original_path,
            "target_file": target_path,
            "format": fmt,
            "converted": converted,
            "size_bytes": size,
            "elapsed_seconds": round(elapsed, 3),
            "speed_bytes_per_sec": int(speed),
            "url": url,
            "content_type": content_type,
            "detected_format": sniffed,
        }


def _excel_to_csv(source: str, target: str, src_ext: str) -> None:
    """Convert an Excel workbook to CSV (largest sheet wins)."""
    import csv

    if src_ext == "xls":
        import xlrd

        wb = xlrd.open_workbook(source)
        ws = max(wb.sheets(), key=lambda s: s.nrows * s.ncols)
        with Path(target).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in range(ws.nrows):
                w.writerow(ws.row_values(r))
    else:
        import openpyxl

        wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
        ws = max(wb.worksheets, key=lambda s: (s.max_row or 0) * (s.max_column or 0))
        with Path(target).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for row in ws.iter_rows(values_only=True):
                w.writerow(["" if v is None else v for v in row])
