#!/usr/bin/env python3
"""Geocode the venues the event sources name into venues.csv, at inventory time (T-5083).

Input: a CSV with the columns `town,place`, one row per venue text as a source writes it (a run report's
refused events, or the venue fields read while probing a source). Each place not yet in venues.csv for its
town is looked up on OpenStreetMap Nominatim, one request a second with the inventory User-Agent. A hit is
kept only when it is a building, an amenity or an address in that town: a town, a village, a district or a
street gives no row, because an event is never placed at a town's centre (owner 2026-10-20).

    python3 seeds/bbsk-events/geocode-venues.py places.csv          # print the rows it would add
    python3 seeds/bbsk-events/geocode-venues.py places.csv --write  # append them to venues.csv

Rows it adds say `nominatim` in `checked_by`; a person who opens the OSM object and confirms it sets `hand`.
The pipelines never call Nominatim: generate.py reads venues.csv into each source's mapping.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENUES = HERE / "venues.csv"
SEARCH = "https://nominatim.openstreetmap.org/search"
UA = "joinedcontext-platform-events-inventory/1.0 (+https://dev.joinedcontext.com)"
#: An answer bigger than this is no Nominatim answer of one hit.
MAX_BYTES = 1 << 20
#: Nominatim's usage policy: at most one request a second.
PAUSE = 1.0
#: Areas and lines: a hit of one of these is no venue.
AREAS = {
    "city", "town", "village", "hamlet", "municipality", "suburb", "quarter", "neighbourhood", "borough",
    "city_district", "district", "county", "state", "region", "country", "postcode", "locality", "road",
    "isolated_dwelling", "farm", "allotments", "square",
}
#: A `place` is a settlement or a part of one (cadastral_community is the village itself); `information` a map board.
REFUSED_CATEGORIES = {"boundary", "highway", "landuse", "natural", "waterway", "railway", "route", "place", "information"}
#: Slovakia's bounding box, the one the events' common mapping keeps too.
LAT = (47.7, 49.7)
LON = (16.8, 22.6)
FIELDS = ["town", "match", "regional", "venue", "streetAddress", "addressLocality", "lat", "lon", "osm", "checked_on", "checked_by"]


def slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def key(place: str) -> str:
    """The venue's match key, as pipelines/common.yaml computes it from the source's text."""
    text = re.sub(r"\([^)]*\)", " ", place.lower())
    return re.sub(r"\s+", " ", re.sub(r"[,;]", " ", text)).strip()


def queries(place: str, town: str) -> list[str]:
    """The whole text, then each part that holds a house number, then the first part: each with the town."""
    parts = [p.strip() for p in re.sub(r"\([^)]*\)", " ", place).split(",") if p.strip()]
    numbered = [p for p in parts if re.search(r"\D \d+[a-zA-Z]?(/\d+[a-zA-Z]?)?$", p)]
    out = []
    for q in [", ".join(parts), *numbered, *parts[:1]]:
        q = f"{q}, {town}"
        if q not in out:
            out.append(q)
    return out


def locality(address: dict) -> str | None:
    for k in ("city", "town", "village", "municipality"):
        if address.get(k):
            return address[k]
    return None


def accepted(hit: dict, town: str) -> str | None:
    """None when the hit is a venue in the town, else why not."""
    category, kind = hit.get("category") or hit.get("class"), hit.get("type")
    if category in REFUSED_CATEGORIES or kind in AREAS or hit.get("addresstype") in AREAS:
        return f"{category}/{kind} is an area or a line, no venue"
    if (hit.get("name") or "").casefold() == town.casefold():
        return f"{hit.get('name')} is the town itself, no venue"
    found = locality(hit.get("address") or {})
    if not found or found.casefold() != town.casefold():
        return f"in {found or 'no town'}, not in {town}"
    lat, lon = float(hit["lat"]), float(hit["lon"])
    if not (LAT[0] <= lat <= LAT[1] and LON[0] <= lon <= LON[1]):
        return "outside Slovakia"
    return None


def fetch(query: str) -> list[dict]:
    url = SEARCH + "?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 3, "countrycodes": "sk"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as answer:
        body = answer.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"answer over {MAX_BYTES} bytes")
    return json.loads(body)


def geocode(town: str, place: str, search: Callable[[str], list[dict]], pause: Callable[[], None]) -> tuple[dict | None, str]:
    """The venues.csv row for the place, or None and why none."""
    why = "no hit"
    for query in queries(place, town):
        pause()
        for hit in search(query):
            why = accepted(hit, town) or ""
            if why:
                continue
            address = hit.get("address") or {}
            street = " ".join(v for v in (address.get("road"), address.get("house_number")) if v)
            return {
                "town": slug(town),
                "match": key(place),
                "regional": "n",
                "venue": place.strip(),
                "streetAddress": street,
                "addressLocality": town,
                "lat": f"{float(hit['lat']):.7f}",
                "lon": f"{float(hit['lon']):.7f}",
                "osm": f"{hit['osm_type']}/{hit['osm_id']}",
                "checked_on": datetime.date.today().isoformat(),
                "checked_by": "nominatim",
            }, query
    return None, why


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("places", type=Path, help="CSV with the columns town,place")
    parser.add_argument("--write", action="store_true", help="append the rows to venues.csv")
    args = parser.parse_args(argv)
    known = {(v["town"], v["match"]) for v in csv.DictReader(VENUES.open(encoding="utf-8"))}
    rows, last = [], [0.0]

    def pause() -> None:
        wait = last[0] + PAUSE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()

    for item in csv.DictReader(args.places.open(encoding="utf-8")):
        town, place = item["town"].strip(), item["place"].strip()
        if not town or not place or (slug(town), key(place)) in known:
            continue
        row, note = geocode(town, place, fetch, pause)
        print(f"{'+' if row else '-'} {town} | {place} | {note}", file=sys.stderr)
        if row:
            known.add((row["town"], row["match"]))
            rows.append(row)
    if args.write and rows:
        with VENUES.open("a", encoding="utf-8", newline="") as out:
            csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n").writerows(rows)
    else:
        csv.DictWriter(sys.stdout, fieldnames=FIELDS, lineterminator="\n").writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
