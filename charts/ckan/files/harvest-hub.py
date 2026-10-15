"""Harvests outside open-data catalogues into CKAN organizations, corrected (T-4152).

Runs as `python3 -c` in the catalogue's image, from the harvest CronJob of a `harvest.sources`
entry with `kind: hub` (its `HARVEST_CONFIG`). The Hub's search API is read whole, filtered and
corrected, and written through the CKAN action API with the catalogue's API token. A dataset this job made
carries the extras `harvest_source` and `source_id`; nothing else in the organization is
touched, and a dataset is withdrawn only after a complete read of its source no longer lists it.

Fetched text is data: it becomes a title, a description or a link, never an instruction, and
a link outside the source's `allowedHosts` is dropped. TLS verification stays on. Prints counts and
dataset names, never the token.
"""
import hashlib
import html.parser
import http.client
import json
import os
import re
import sys
import time
import unicodedata
import uuid
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY = 32 * 1024 * 1024
MAX_LAYERS = 10
USER_AGENT = "joinedcontext-harvest/1 (+https://github.com/marek-mraz/joinedcontext-deployment)"
# The source's licence code -> CKAN's licence register id and the licence's own page.
LICENCES = {
    "CC-BY-4.0": ("cc-by", "https://creativecommons.org/licenses/by/4.0/"),
    "CC-BY-SA-4.0": ("cc-by-sa", "https://creativecommons.org/licenses/by-sa/4.0/"),
    "CC0-1.0": ("cc-zero", "https://creativecommons.org/publicdomain/zero/1.0/"),
}


class SourceError(Exception):
    """The source could not be read whole; nothing of it is written or withdrawn."""


def fetch_json(url, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise SourceError(f"{url}: answer larger than {MAX_BODY} bytes")
            return json.loads(body)
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as error:
            if attempt == attempts - 1:
                raise SourceError(f"{url}: {error}") from error
            time.sleep(2 ** attempt)


class _Text(html.parser.HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(markup):
    """The source's HTML description as plain paragraphs: no tag, style or link survives."""
    parser = _Text()
    parser.feed(markup or "")
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n\n".join(line for line in lines if line)[:10000]


def slug(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def iso(millis):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(millis / 1000)) if millis else None


def allowed(url, hosts):
    parts = urllib.parse.urlsplit(url or "")
    return parts.scheme == "https" and parts.hostname in hosts


def corrected_title(item, source):
    title = source.get("titles", {}).get(item["id"], item["title"])
    for wrong, right in source.get("spelling", {}).items():
        title = title.replace(wrong, right)
    return " ".join(title.split())


def select(items, source):
    """Which source items become datasets, under which title, and why each other one does not.
    Returns (kept, skipped): kept as (item, title), skipped as (id, title, reason)."""
    kept, skipped = [], []
    for item in items:
        title = corrected_title(item, source)
        reason = source.get("skip", {}).get(item["id"])
        if reason:
            skipped.append((item["id"], title, reason))
        elif item.get("type") not in ("Feature Service", "Shapefile"):
            skipped.append((item["id"], title, f"type {item.get('type')} is not a dataset"))
        elif item.get("license") not in LICENCES:
            skipped.append((item["id"], title, f"no open licence ({item.get('license')})"))
        else:
            kept.append((item, title))
    # One title, one dataset: the newest copy stays, an older one is named as its duplicate.
    newest = {}
    for item, title in kept:
        if title not in newest or item.get("modified", 0) > newest[title].get("modified", 0):
            newest[title] = item
    unique = []
    for item, title in kept:
        if newest[title] is item:
            unique.append((item, title))
        else:
            skipped.append((item["id"], title, f"duplicate of {newest[title]['id']}"))
    return unique, skipped


def resources(item, layers, source):
    hub, hosts = source["hub"], set(source["allowedHosts"])
    found = []
    if item["type"] == "Feature Service":
        many = len(layers) > 1
        for layer in layers[:MAX_LAYERS]:
            label = f"{' '.join(layer['name'].split())} " if many else ""
            download = f"{hub}/api/download/v1/items/{item['id']}"
            found.append({"name": f"{label}CSV", "format": "CSV", "mimetype": "text/csv",
                          "url": f"{download}/csv?layers={layer['id']}"})
            if layer.get("geometryType"):
                found.append({"name": f"{label}GeoJSON", "format": "GeoJSON",
                              "mimetype": "application/geo+json",
                              "url": f"{download}/geojson?layers={layer['id']}"})
        found.append({"name": "ArcGIS REST API", "format": "Esri REST", "url": item.get("url")})
    else:
        found.append({"name": "Shapefile", "format": "SHP", "mimetype": "application/zip",
                      "url": f"https://www.arcgis.com/sharing/rest/content/items/{item['id']}/data"})
    return [r for r in found if allowed(r["url"], hosts)]


def dataset(item, title, layers, source):
    """The CKAN package for one kept item. `name` is only a proposal: a dataset that already
    exists keeps its own."""
    licence_id, licence_url = LICENCES[item["license"]]
    tags = {t.strip() for t in item.get("tags") or []}
    tags |= {c.rsplit("/", 1)[-1].strip() for c in item.get("categories") or []}
    extras = {
        "harvest_source": source["source"],
        "source_id": item["id"],
        "source_url": f"{source['hub']}/datasets/{item['id']}",
        "issued": iso(item.get("created")),
        "modified": iso(item.get("modified")),
        "publisher_name": source["publisherName"],
        "publisher_uri": source["publisherUri"],
        "license_url": licence_url,
    }
    package = {
        # A fixed id per source item, so a dataset withdrawn earlier (which search no longer
        # shows) is found again by `package_show` and revived instead of clashing on its name.
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source['hub']}/datasets/{item['id']}")),
        "name": f"{source['organization']}-{slug(title)[:70].strip('-')}-{item['id'][:6]}",
        "title": title,
        "owner_org": source["organization"],
        "notes": plain_text(item.get("description")) or plain_text(item.get("snippet")),
        "license_id": licence_id,
        "url": extras["source_url"],
        "tags": [{"name": t} for t in sorted(tags) if re.fullmatch(r"[\w .-]{2,100}", t)],
        "resources": resources(item, layers, source),
        "extras": [{"key": k, "value": v} for k, v in sorted(extras.items()) if v],
    }
    digest = hashlib.sha256(json.dumps(package, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    package["extras"].append({"key": "harvest_hash", "value": digest})
    return package


def extra(package, key):
    return next((e["value"] for e in package.get("extras", []) if e["key"] == key), None)


class Ckan:
    def __init__(self, host, token):
        self.host, _, port = host.partition(":")
        self.port = int(port or 5000)
        self.token = token

    def call(self, action, payload):
        body = json.dumps(payload).encode()
        conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        try:
            conn.request("POST", f"/api/3/action/{action}", body,
                         {"Authorization": self.token, "Content-Type": "application/json"})
            response = conn.getresponse()
            answer = json.loads(response.read() or b"{}")
        finally:
            conn.close()
        if not answer.get("success"):
            error = answer.get("error", {})
            raise RuntimeError(f"{action}: HTTP {response.status} {error.get('__type', '')} "
                               f"{ {k: v for k, v in error.items() if k != '__type'} }")
        return answer["result"]

    def show(self, action, ident):
        """The object, or None when CKAN does not know it."""
        try:
            return self.call(action, {"id": ident})
        except RuntimeError as error:
            if "Not Found" in str(error):
                return None
            raise


def harvested(ckan, source):
    """This source's active datasets in the organization, by source item id."""
    found, start = {}, 0
    while True:
        page = ckan.call("package_search", {"fq": f"organization:{source['organization']}", "rows": 1000,
                                            "start": start, "include_private": True})
        for package in page["results"]:
            if extra(package, "harvest_source") == source["source"]:
                found[extra(package, "source_id")] = package
        start += len(page["results"])
        if not page["results"] or start >= page["count"]:
            return found


def hub_items(source):
    items, url = [], f"{source['hub']}/api/search/v1/collections/dataset/items?limit=100"
    matched = None
    while url:
        page = fetch_json(url)
        matched = page.get("numberMatched", matched)
        items += [f["properties"] for f in page.get("features", [])]
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
        if url and not allowed(url, {urllib.parse.urlsplit(source["hub"]).hostname}):
            raise SourceError(f"next page outside the hub: {url}")
    if matched is None or len(items) != matched:
        raise SourceError(f"read {len(items)} of {matched} items")
    return items


def item_layers(item):
    if item["type"] != "Feature Service":
        return []
    service = fetch_json(f"{item['url']}?f=json")
    tables = [{**t, "geometryType": None} for t in service.get("tables", [])]
    return service.get("layers", []) + tables


def warm_downloads(package):
    """The Hub builds an export on its first request and answers 202 until it is ready; one
    request per new or changed download here means a visitor gets the file, not the wait."""
    for resource in package["resources"]:
        if resource["format"] in ("CSV", "GeoJSON"):
            request = urllib.request.Request(resource["url"], headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    response.read(1)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                print(f"  could not prepare {resource['url']}: {error}", file=sys.stderr)
            time.sleep(0.5)


def harvest(ckan, source, items, layers_of, warm=lambda package: None):
    kept, skipped = select(items, source)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "withdrawn": 0}
    if ckan.show("organization_show", source["organization"]) is None:
        ckan.call("organization_create", {"name": source["organization"], "title": source["publisherName"],
                                          "description": source.get("publisherDescription", "")})
    existing = harvested(ckan, source)
    for item, title in kept:
        package = dataset(item, title, layers_of(item), source)
        old = existing.pop(item["id"], None) or ckan.show("package_show", package["id"])
        if old is None:
            ckan.call("package_create", package)
            warm(package)
            counts["created"] += 1
        elif extra(old, "harvest_hash") == extra(package, "harvest_hash") and old.get("state") == "active":
            counts["unchanged"] += 1
        else:
            package["name"] = old["name"]
            package["id"] = old["id"]
            package["state"] = "active"
            ckan.call("package_update", package)
            warm(package)
            counts["updated"] += 1
    for package in existing.values():
        if package.get("state") == "active":
            ckan.call("package_delete", {"id": package["id"]})
            counts["withdrawn"] += 1
    return counts, kept, skipped


def main():
    ckan = Ckan(os.environ["CATALOGUE"], os.environ["CKAN_API_TOKEN"])
    source = json.loads(os.environ["HARVEST_CONFIG"])
    try:
        items = hub_items(source)
        counts, kept, skipped = harvest(ckan, source, items, item_layers, warm_downloads)
    except (SourceError, RuntimeError, OSError) as error:
        print(f"{source['source']}: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"{source['source']}: {len(items)} items, {len(kept)} datasets "
          + ", ".join(f"{k} {v}" for k, v in counts.items()) + f", skipped {len(skipped)}")
    for ident, title, reason in skipped:
        print(f"  skipped {ident} {title!r}: {reason}")


if __name__ == "__main__":
    main()
