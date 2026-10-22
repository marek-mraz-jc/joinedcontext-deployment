#!/usr/bin/env python3
"""Count a store's events per source and where each event's point came from (T-5135).

Reads every Event of an events store through its public NGSI-LD API (or a JSON file of keyValues
entities), and prints per source: the events, how many carry a GPS point, and whether the point came
from the feed itself, from a venues.csv row a person checked (`hand`), from a `nominatim` row, or from
the source's own address in homes.csv (`home`). The last line is the store's geocoded share, the
number the owner's rule holds at >= 90 % (owner 2026-10-22).

`--places FILE` writes the events without a point that name a venue as `town,place` rows, the input of
geocode-venues.py: report, geocode, review the rows by hand, regenerate.

    python3 seeds/bbsk-events/report.py --url https://api.dev.joinedcontext.com/api/endpoint/<slug>/ngsi-ld/v1
    python3 seeds/bbsk-events/report.py --file events.json --places places.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "joinedcontext-platform-events-inventory/1.0 (+https://dev.joinedcontext.com)"
#: One page of the NGSI-LD API, and a cap on pages: a store keeps at most 100 events per source.
PAGE = 1000
MAX_PAGES = 50
MAX_BYTES = 64 << 20
ORIGINS = ("feed", "home", "hand", "nominatim")


def inventory() -> dict[str, dict]:
    """The inventory rows by their events page, the `source` every Event names."""
    return {
        r["events_url"]: r
        for f in ("sources.csv", "sources-sk.csv")
        for r in csv.DictReader((HERE / f).open(encoding="utf-8"))
        if r["decision"] == "pipeline"
    }


def points() -> dict[tuple[float, float], str]:
    """Each venue point of venues.csv with who checked it; a source's home is `home`."""
    venues = list(csv.DictReader((HERE / "venues.csv").open(encoding="utf-8")))
    out = {(round(float(v["lon"]), 7), round(float(v["lat"]), 7)): v["checked_by"] for v in venues}
    homes = {(h["town"], h["match"]) for h in csv.DictReader((HERE / "homes.csv").open(encoding="utf-8"))}
    for v in venues:
        if (v["town"], v["match"]) in homes:
            out[(round(float(v["lon"]), 7), round(float(v["lat"]), 7))] = "home"
    return out


def origin(event: dict, known: dict[tuple[float, float], str]) -> str | None:
    location = event.get("location")
    if not isinstance(location, dict) or location.get("type") != "Point":
        return None
    lon, lat = location["coordinates"][:2]
    return known.get((round(lon, 7), round(lat, 7)), "feed")


def summarise(events: list[dict], known: dict[tuple[float, float], str]) -> dict:
    """Per source: events, with a point, by origin; and the venues named by events without a point."""
    per: dict[str, Counter] = defaultdict(Counter)
    unplaced: Counter = Counter()
    for event in events:
        source = event.get("source") or "-"
        how = origin(event, known)
        per[source]["events"] += 1
        if how:
            per[source]["gps"] += 1
            per[source][how] += 1
        elif event.get("venue"):
            unplaced[(source, event["venue"])] += 1
    total = sum(c["events"] for c in per.values())
    gps = sum(c["gps"] for c in per.values())
    return {"sources": per, "total": total, "gps": gps, "share": gps / total if total else 0.0, "unplaced": unplaced}


def fetch(base: str) -> list[dict]:
    """Every Event of the store, paged by the API's cursor."""
    url = base.rstrip("/") + "/entities?" + urllib.parse.urlencode(
        {"type": "Event", "limit": PAGE, "format": "keyValues", "attrs": "source,location,venue"}
    )
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("the store's URL must be https")
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as answer:
            body = answer.read(MAX_BYTES + 1)
            link = answer.headers.get_all("Link") or []
        if len(body) > MAX_BYTES:
            raise ValueError(f"answer over {MAX_BYTES} bytes")
        out += json.loads(body)
        nxt = [part.split(">")[0].lstrip(" <") for part in ",".join(link).split(",") if 'rel="next"' in part]
        if not nxt:
            return out
        url = urllib.parse.urljoin(url, nxt[0])
    raise ValueError(f"more than {MAX_PAGES} pages")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    given = parser.add_mutually_exclusive_group(required=True)
    given.add_argument("--url", help="the store's NGSI-LD API base, ending in /ngsi-ld/v1")
    given.add_argument("--file", type=Path, help="a JSON array of keyValues Event entities")
    parser.add_argument("--places", type=Path, help="write town,place rows of the unplaced venues here")
    args = parser.parse_args(argv)
    events = fetch(args.url) if args.url else json.loads(args.file.read_text(encoding="utf-8"))
    report = summarise(events, points())
    print("source\tevents\tgps\t" + "\t".join(ORIGINS))
    for source, c in sorted(report["sources"].items(), key=lambda kv: -kv[1]["events"]):
        print(f"{source}\t{c['events']}\t{c['gps']}\t" + "\t".join(str(c[o]) for o in ORIGINS))
    print(f"{len(report['sources'])} sources, {report['total']} events, {report['gps']} with GPS ({report['share']:.0%})")
    if args.places:
        rows = inventory()
        with args.places.open("w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(["town", "place"])
            for source, place in sorted({k for k in report["unplaced"]}):
                town = rows.get(source, {}).get("town")
                if town:
                    writer.writerow([town, place])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
