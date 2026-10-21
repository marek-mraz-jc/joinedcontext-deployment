"""The platform's standard APIs of a converted dataset, as distributions of its catalogue page (T-4279).

Prepended to each harvest script by templates/harvest.yaml. The harvest replaces a dataset's
resource list on every run, so the distributions are part of what it writes, not added beside it
by something the next night would erase. `OD_DATASETS` is charts/ckan/files/od-datasets.json, which
scripts/open-data/generate.py writes from the mapping: per CKAN dataset name, the open-data
Endpoint's slug, the entity type its rows became, whether they carry a location and whether its
rows name their catalogue dataset (`filtered`, false for a dataset an older seed reads whole) and
whether its type holds only its rows on that Endpoint (`sole`).
`OD_GATEWAY` is the public base the Endpoints answer under; without it no dataset gains any.
A dataset with no distributions is withdrawn by the harvest (EP-118, T-4324): the catalogue lists
NGSI-LD data with all its doors and its data model, or not at all.
CKAN holds no rows of any of them: the Endpoint is the data (T-5060).
"""
import json as _json
import os as _os
import sys as _sys
import time as _time
import urllib.error as _error
import urllib.parse as _parse
import urllib.request as _request

OD_DATASETS = _json.loads(_os.environ.get("OD_DATASETS") or "{}")
OD_GATEWAY = (_os.environ.get("OD_GATEWAY") or "").rstrip("/")

# (path under the Endpoint, name, format, media type, conformsTo, how it keeps the dataset's rows, what
# its rows must have for it to be listed: a `location`, a `series` of measured numbers, or nothing).
# The format is the label jcctl's publisher gives an Endpoint's own dataset (ckan.rs `distribution`),
# so the catalogue's format facet counts both under one name (EP-118, T-4324).
# Each row names its catalogue dataset in `isPartOf` (T-4289); an address keeps only those rows in
# its standard's own syntax: NGSI-LD and file.csv `q`, OGC API Features the queryable as a parameter,
# OData and SensorThings `$filter`. MCP and WebSocket read every type of the Endpoint, so they list every row and say so.
# file.csv is the one file an Endpoint publishes; a map reads GeoJSON from NGSI-LD (Accept:
# application/geo+json) or OGC API Features (API/02 §3, T-4597).
OD_STANDARDS = [
    # application/json: what an anonymous GET without Accept answers, the @context in the Link header
    # (CIM 009 6.3.6); ld+json only when Accept asks for it (T-4539).
    ("ngsi-ld/v1/entities", "NGSI-LD API", "NGSI-LD", "application/json",
     "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/", "q", None),
    ("file.csv", "CSV", "CSV", "text/csv", None, "q", None),
    ("ogc/features/collections/{type}/items", "OGC API - Features", "OGCFEAT", "application/geo+json",
     "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core", "ogc", "location"),
    ("odata/v4/{type}", "OData v4", "OData", "application/json", "https://docs.oasis-open.org/odata/odata/v4.01/", "odata", None),
    ("sta/v1.1/Datastreams", "SensorThings API", "STA", "application/json", "http://www.opengis.net/spec/iot_sensing/1.1",
     "odata", "series"),
    ("mcp", "Model Context Protocol", "MCP", "application/json", "https://modelcontextprotocol.io/specification", None, None),
    ("ws", "WebSocket", "WebSocket", "application/json", None, None, None),
]


# The data model in every formalism (EP-118): the file an Endpoint serves under schema/v{n}/, and
# the label jcctl's publisher gives it (ckan.rs `format_of`).
OD_MODEL_FILES = {
    "model.schema.json": "JSON Schema", "context.jsonld": "JSON-LD", "model.linkml.yaml": "LinkML",
    "model.md": "Markdown", "model.owl.ttl": "OWL", "model.rdf.ttl": "RDF", "model.shacl.ttl": "SHACL",
}
_OD_MODELS = {}


# The waits before each retry of a read the network broke (T-4385): a reset or a 5xx during a
# mesh restart passes in seconds to minutes; a 4xx is the answer and is not asked again.
OD_RETRY_WAITS = (5, 30, 120)


def _od_transient(error):
    """Whether an HTTP error passes by itself: the edge's 429 (T-4717) or a 5xx."""
    return error.code == 429 or error.code >= 500


def od_read(url, accept="application/json", limit=64 * 1024 * 1024):
    """The body of an anonymous GET of `url`, at most `limit` bytes; read again after a broken
    connection, a 429 of the edge or a 5xx. Any other 4xx raises at once: it is the answer."""
    for wait in OD_RETRY_WAITS + (None,):
        try:
            with _request.urlopen(_request.Request(url, headers={"Accept": accept}), timeout=300) as answer:
                body = answer.read(limit + 1)
            if len(body) > limit:
                raise ValueError(f"{url}: answered more than {limit} bytes")
            return body
        except _error.HTTPError as error:
            if not _od_transient(error) or wait is None:
                raise
        except (_error.URLError, ConnectionError, TimeoutError):
            if wait is None:
                raise
        print(f"{url}: read failed, again in {wait} s", file=_sys.stderr)
        _time.sleep(wait)


def od_models(endpoint):
    """The models of Endpoint `endpoint`, as its `schema/index.json` lists them, read once a run.
    A failed read raises: a gateway that does not answer is an outage, not a catalogue to empty."""
    if endpoint not in _OD_MODELS:
        url = f"{OD_GATEWAY}/api/endpoint/{_parse.quote(endpoint)}/schema/index.json"
        _OD_MODELS[endpoint] = _json.loads(od_read(url)).get("models") or []
    return _OD_MODELS[endpoint]


def od_model_files(root, endpoint, kind):
    """One distribution per artefact of the newest model that defines `kind`, with its sha256, or
    none when that model lacks one of the seven (EP-118 lists them all or the dataset is out)."""
    models = [m for m in od_models(endpoint) if kind in (m.get("types") or [])]
    if not models:
        return []
    model = max(models, key=lambda m: m.get("version") or 0)
    artefacts = model.get("artifacts") or {}
    if not set(OD_MODEL_FILES) <= set(artefacts):
        return []
    return [{"name": f"Data model: {label}", "url": f"{root}schema/v{model['version']}/{file}",
             "format": label, "mimetype": artefacts[file].get("type"), "size": artefacts[file].get("bytes"),
             "hash": artefacts[file].get("sha256"), "hash_algorithm": "sha256",
             "description": f"The data model of {kind} as {label}; sha256 {artefacts[file].get('sha256')}."}
            for file, label in OD_MODEL_FILES.items()]


def _od_address(entry, path, filtered):
    """The URL of `path` under the dataset's Endpoint, keeping only its rows the way `filtered`
    says (`q`, `ogc`, `odata`) or every row of its type (None)."""
    root = f"{OD_GATEWAY}/api/endpoint/{entry['endpoint']}/"
    dataset = entry["dataset"]
    mine = {
        "q": _parse.urlencode({"type": entry["type"], "q": f'isPartOf=="{dataset}"'}),
        "ogc": _parse.urlencode({"isPartOf": dataset}),
        # OData string literals double a quote (OData 4.01 ABNF `SQUOTE-in-string`); a space is
        # %20, since `+` is a space only in form encoding, not in OData's URL conventions. SensorThings
        # is OData too: the gateway reads this `$filter` as the same `q` (T-4288).
        "odata": _parse.urlencode({"$filter": "isPartOf eq '" + dataset.replace("'", "''") + "'"},
                                  quote_via=_parse.quote),
    }
    url = root + path.replace("{type}", _parse.quote(entry["type"]))
    if path == "ws":
        url = "wss" + url[len("https"):] if url.startswith("https") else url
    if filtered:
        url += "?" + mine[filtered]
    return url


def _od_filter(entry, filtered):
    """How a standard keeps the dataset's rows on its Endpoint, None for every row of the type.
    A dataset an older seed reads whole: its rows name no catalogue dataset (T-4291). One whose
    type holds its rows alone on the door is kept by the type: a `q` cannot be counted or paged
    in parallel, and timed out on 26 862 rows (`sole`, T-4540)."""
    return filtered if entry.get("filtered", True) and not entry.get("sole", False) else None


def od_extras(name):
    """The `endpoint` extra of CKAN dataset `name` (T-4765): its Endpoint's public URL, the value
    jcctl's publisher writes for an Endpoint's own dataset (ckan.rs, `{url}/`), so the catalogue
    and its readers find every dataset's Endpoint under one key. None for an unconverted one."""
    entry = OD_DATASETS.get(name)
    if not entry or not OD_GATEWAY:
        return []
    return [{"key": "endpoint", "value": f"{OD_GATEWAY}/api/endpoint/{entry['endpoint']}/"}]


def od_standards(name):
    """The distributions of CKAN dataset `name` (EP-118), or none when it cannot list them all:
    its rows were not converted, or its Endpoint's model lacks an artefact. A harvest withdraws a
    dataset with none."""
    entry = OD_DATASETS.get(name)
    if not entry or not OD_GATEWAY:
        return []
    root = f"{OD_GATEWAY}/api/endpoint/{entry['endpoint']}/"
    model = od_model_files(root, entry["endpoint"], entry["type"])
    if not model:
        return []
    out = []
    for path, title, fmt, media, conforms, filtered, needs in OD_STANDARDS:
        if needs and not entry.get(needs):
            continue
        filtered = _od_filter(entry, filtered)
        what = ("These rows" if filtered or entry.get("sole", False)
                else f"Every {entry['type']} of the space, these rows among them")
        resource = {"name": f"{title} ({entry['type']})", "url": _od_address(entry, path, filtered),
                    "format": fmt, "mimetype": media, "resource_type": "api",
                    "description": f"{what}, through the platform's {title} (NGSI-LD data, read-only)."}
        if conforms:
            resource["conforms_to"] = conforms
        out.append(resource)
    return out + model
