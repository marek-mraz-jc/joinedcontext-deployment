"""The platform's standard APIs of a converted dataset, as distributions of its catalogue page (T-4279).

Prepended to each harvest script by templates/harvest.yaml. The harvest replaces a dataset's
resource list on every run, so the distributions are part of what it writes, not added beside it
by something the next night would erase. `OD_DATASETS` is charts/ckan/files/od-datasets.json, which
scripts/open-data/generate.py writes from the mapping: per CKAN dataset name, the open-data
Endpoint's slug, the entity type its rows became and whether they carry a location.
`OD_GATEWAY` is the public base the Endpoints answer under; without it no dataset gains any.
A dataset with no distributions is withdrawn by the harvest (EP-118, T-4324): the catalogue lists
NGSI-LD data with all its doors and its data model, or not at all.
"""
import json as _json
import os as _os
import urllib.parse as _parse
import urllib.request as _request

OD_DATASETS = _json.loads(_os.environ.get("OD_DATASETS") or "{}")
OD_GATEWAY = (_os.environ.get("OD_GATEWAY") or "").rstrip("/")

# (path under the Endpoint, name, format, media type, conformsTo, filtered to the dataset, needs a location)
# The format is the label jcctl's publisher gives an Endpoint's own dataset (ckan.rs `distribution`),
# so the catalogue's format facet counts both under one name (EP-118, T-4324).
# OGC API Features and OData read a whole type: their views refuse a filter on `dataset` (403),
# so those two list every row of the type in the space, and say so.
OD_STANDARDS = [
    ("ngsi-ld/v1/entities", "NGSI-LD API", "NGSI-LD", "application/ld+json",
     "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/", True, False),
    ("file.geojson", "GeoJSON", "GeoJSON", "application/geo+json", "https://www.rfc-editor.org/rfc/rfc7946", True, True),
    ("file.csv", "CSV", "CSV", "text/csv", None, True, False),
    ("file.json", "JSON", "JSON", "application/json", None, True, False),
    ("file.xlsx", "Excel", "XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", None, True, False),
    ("ogc/features/collections/{type}/items", "OGC API - Features", "OGCFEAT", "application/geo+json",
     "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core", False, True),
    ("odata/v4/{type}", "OData v4", "OData", "application/json", "https://docs.oasis-open.org/odata/odata/v4.01/", False, False),
    ("mcp", "Model Context Protocol", "MCP", "application/json", "https://modelcontextprotocol.io/specification", False, False),
    ("ws", "WebSocket", "WebSocket", "application/json", None, False, False),
]


# The data model in every formalism (EP-118): the file an Endpoint serves under schema/v{n}/, and
# the label jcctl's publisher gives it (ckan.rs `format_of`).
OD_MODEL_FILES = {
    "model.schema.json": "JSON Schema", "context.jsonld": "JSON-LD", "model.linkml.yaml": "LinkML",
    "model.md": "Markdown", "model.owl.ttl": "OWL", "model.rdf.ttl": "RDF", "model.shacl.ttl": "SHACL",
}
_OD_MODELS = {}


def od_models(endpoint):
    """The models of Endpoint `endpoint`, as its `schema/index.json` lists them, read once a run.
    A failed read raises: a gateway that does not answer is an outage, not a catalogue to empty."""
    if endpoint not in _OD_MODELS:
        url = f"{OD_GATEWAY}/api/endpoint/{_parse.quote(endpoint)}/schema/index.json"
        with _request.urlopen(_request.Request(url, headers={"Accept": "application/json"}), timeout=60) as answer:
            _OD_MODELS[endpoint] = _json.load(answer).get("models") or []
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
    mine = _parse.urlencode({"type": entry["type"], "q": f'dataset=="{entry["dataset"]}"'})
    out = []
    for path, title, fmt, media, conforms, filtered, located in OD_STANDARDS:
        if located and not entry.get("location"):
            continue
        url = root + path.replace("{type}", _parse.quote(entry["type"]))
        if path == "ws":
            url = "wss" + url[len("https"):] if url.startswith("https") else url
        if filtered:
            url += "?" + mine
        what = ("These rows" if filtered else f"Every {entry['type']} of the space, these rows among them")
        resource = {"name": f"{title} ({entry['type']})", "url": url, "format": fmt, "mimetype": media,
                    "resource_type": "api",
                    "description": f"{what}, through the platform's {title} (NGSI-LD data, read-only)."}
        if conforms:
            resource["conforms_to"] = conforms
        out.append(resource)
    return out + model
