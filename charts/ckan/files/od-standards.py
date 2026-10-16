"""The platform's standard APIs of a converted dataset, as distributions of its catalogue page (T-4279).

Prepended to each harvest script by templates/harvest.yaml. The harvest replaces a dataset's
resource list on every run, so the distributions are part of what it writes, not added beside it
by something the next night would erase. `OD_DATASETS` is charts/ckan/files/od-datasets.json, which
scripts/open-data/generate.py writes from the mapping: per CKAN dataset name, the open-data
Endpoint's slug, the entity type its rows became and whether they carry a location.
`OD_GATEWAY` is the public base the Endpoints answer under; without it no dataset gains any.
"""
import json as _json
import os as _os
import urllib.parse as _parse

OD_DATASETS = _json.loads(_os.environ.get("OD_DATASETS") or "{}")
OD_GATEWAY = (_os.environ.get("OD_GATEWAY") or "").rstrip("/")

# (path under the Endpoint, name, format, media type, conformsTo, filtered to the dataset, needs a location)
# OGC API Features and OData read a whole type: their views refuse a filter on `dataset` (403),
# so those two list every row of the type in the space, and say so.
OD_STANDARDS = [
    ("ngsi-ld/v1/entities", "NGSI-LD API", "JSON-LD", "application/ld+json",
     "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/", True, False),
    ("file.geojson", "GeoJSON", "GeoJSON", "application/geo+json", "https://www.rfc-editor.org/rfc/rfc7946", True, True),
    ("file.csv", "CSV", "CSV", "text/csv", None, True, False),
    ("file.json", "JSON", "JSON", "application/json", None, True, False),
    ("file.xlsx", "Excel", "XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", None, True, False),
    ("ogc/features/collections/{type}/items", "OGC API - Features", "GeoJSON", "application/geo+json",
     "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core", False, True),
    ("odata/v4/{type}", "OData v4", "JSON", "application/json", "https://docs.oasis-open.org/odata/odata/v4.01/", False, False),
    ("mcp", "Model Context Protocol", "JSON", "application/json", "https://modelcontextprotocol.io/specification", False, False),
    ("ws", "WebSocket", "JSON", "application/json", None, False, False),
]


def od_standards(name):
    """The distributions of CKAN dataset `name`, or none when it was not converted."""
    entry = OD_DATASETS.get(name)
    if not entry or not OD_GATEWAY:
        return []
    root = f"{OD_GATEWAY}/api/endpoint/{entry['endpoint']}/"
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
    return out
