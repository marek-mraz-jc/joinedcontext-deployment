"""Harvests outside open-data catalogues into CKAN organizations, corrected (T-4152).

Runs as `python3 -c` in the catalogue's image, from the harvest CronJob of a `harvest.sources`
entry with `kind: hub` (its `HARVEST_CONFIG`). The Hub's search API is read whole, filtered and
corrected, and written through the CKAN action API with the catalogue's API token. A dataset this job made
carries the extras `harvest_source` and `source_id`; nothing else in the organization is
touched, and a dataset is withdrawn only after a complete read of its source no longer lists it.

A dataset lists the platform's own distributions of its converted rows and their data model, and
none of the Hub's links (EP-118, T-4324); an item whose rows were not converted is not listed, and
withdrawn if an earlier run listed it. CKAN holds no rows: the Endpoint is the data, and the first
run after T-5060 drops the tables older runs wrote, since their rows no longer move the hash. Fetched text is data: it becomes a title
or a description, never an instruction. TLS verification stays on. Prints counts and dataset names, never the token.
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
USER_AGENT = "joinedcontext-harvest/1 (+https://github.com/marek-mraz/joinedcontext-deployment)"
# The source's licence code -> CKAN's licence register id and the licence's own page.
LICENCES = {
    "CC-BY-4.0": ("cc-by", "https://creativecommons.org/licenses/by/4.0/"),
    "CC-BY-SA-4.0": ("cc-by-sa", "https://creativecommons.org/licenses/by-sa/4.0/"),
    "CC0-1.0": ("cc-zero", "https://creativecommons.org/publicdomain/zero/1.0/"),
}


class SourceError(Exception):
    """The source could not be read whole; nothing of it is written or withdrawn."""


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a host the source allows."""

    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl, self.hosts):
            raise SourceError(f"redirect to {urllib.parse.urlsplit(newurl).hostname} is not an allowed host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_json(url, hosts, attempts=3):
    """The JSON at `url`, fetched over https from `hosts` only, redirects included."""
    if not allowed(url, hosts):
        raise SourceError(f"{url}: not an allowed host")
    opener = urllib.request.build_opener(_CheckedRedirects(hosts))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(attempts):
        try:
            with opener.open(request, timeout=60) as response:
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
        elif item["type"] == "Feature Service" and not allowed(item.get("url"), set(source["allowedHosts"])):
            skipped.append((item["id"], title, "its service is not on an allowed host"))
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


def dataset(item, title, source, name=None):
    """The CKAN package for one kept item, under `name` when the dataset already exists (it keeps
    its own) and a proposed name otherwise. The distributions follow that name, which is the key
    of `od-datasets.json`."""
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
    name = name or f"{source['organization']}-{slug(title)[:70].strip('-')}-{item['id'][:6]}"
    package = {
        # A fixed id per source item, so a dataset withdrawn earlier (which search no longer
        # shows) is found again by `package_show` and revived instead of clashing on its name.
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source['hub']}/datasets/{item['id']}")),
        "name": name,
        "title": title,
        "owner_org": source["organization"],
        "notes": plain_text(item.get("description")) or plain_text(item.get("snippet")),
        "license_id": licence_id,
        "url": extras["source_url"],
        "tags": [{"name": t} for t in sorted(tags) if re.fullmatch(r"[\w .-]{2,100}", t)],
        # The platform's own doors to the rows and their data model; the Hub's CSV, GeoJSON, Esri
        # REST and Shapefile links are not listed (EP-118, T-4324). None means the rows were not
        # converted, and the dataset is withdrawn.
        "resources": od_standards(name),
        "extras": [{"key": k, "value": v} for k, v in sorted(extras.items()) if v] + od_extras(name),
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
        page = fetch_json(url, {urllib.parse.urlsplit(source["hub"]).hostname})
        matched = page.get("numberMatched", matched)
        items += [f["properties"] for f in page.get("features", [])]
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
        if url and not allowed(url, {urllib.parse.urlsplit(source["hub"]).hostname}):
            raise SourceError(f"next page outside the hub: {url}")
    if matched is None or len(items) != matched:
        raise SourceError(f"read {len(items)} of {matched} items")
    return items


def harvest(ckan, source, items):
    kept, skipped = select(items, source)
    if not kept:
        # A Hub that answers nothing (or nothing open) is an outage, not a catalogue to empty.
        raise SourceError(f"the hub listed {len(items)} items and none to keep; nothing is withdrawn")
    counts = {"created": 0, "updated": 0, "unchanged": 0, "withdrawn": 0}
    if ckan.show("organization_show", source["organization"]) is None:
        ckan.call("organization_create", {"name": source["organization"], "title": source["publisherName"],
                                          "description": source.get("publisherDescription", "")})
    existing = harvested(ckan, source)
    packages = []
    for item, title in kept:
        proposed = dataset(item, title, source)
        old = existing.pop(item["id"], None) or ckan.show("package_show", proposed["id"])
        package = dataset(item, title, source, old["name"]) if old else proposed
        if package["resources"]:
            packages.append((item, title, package, old))
        else:
            skipped.append((item["id"], title, "not converted to NGSI-LD, so not listed (EP-118)"))
            if old:
                existing[item["id"]] = old
    if not packages:
        # No dataset converted at all is a missing gateway or mapping, not a catalogue to empty.
        raise SourceError(f"none of {len(kept)} datasets lists the platform's distributions; nothing is withdrawn")
    for item, title, package, old in packages:
        if old is None:
            ckan.call("package_create", package)
            counts["created"] += 1
        elif extra(old, "harvest_hash") == extra(package, "harvest_hash") and old.get("state") == "active":
            counts["unchanged"] += 1
        else:
            package["id"] = old["id"]
            package["state"] = "active"
            ckan.call("package_update", package)
            counts["updated"] += 1
    for package in existing.values():
        if package.get("state") == "active":
            ckan.call("package_delete", {"id": package["id"]})
            counts["withdrawn"] += 1
    return counts, [(item, title) for item, title, _, _ in packages], skipped


def main():
    ckan = Ckan(os.environ["CATALOGUE"], os.environ["CKAN_API_TOKEN"])
    source = json.loads(os.environ["HARVEST_CONFIG"])
    try:
        items = hub_items(source)
        counts, kept, skipped = harvest(ckan, source, items)
    except (SourceError, RuntimeError, OSError) as error:
        print(f"{source['source']}: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"{source['source']}: {len(items)} items, {len(kept)} datasets "
          + ", ".join(f"{k} {v}" for k, v in counts.items()) + f", skipped {len(skipped)}")
    for ident, title, reason in skipped:
        print(f"  skipped {ident} {title!r}: {reason}")


if __name__ == "__main__":
    main()
