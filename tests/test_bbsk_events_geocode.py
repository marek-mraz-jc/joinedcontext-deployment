"""seeds/bbsk-events/geocode-venues.py: a venue's point from its address, never a town's centre (T-5083)."""

import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "seeds/bbsk-events"
spec = importlib.util.spec_from_file_location("geocode_venues", EVENTS / "geocode-venues.py")
geocode_venues = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geocode_venues)


def hit(category: str, kind: str, town: str, lat: str = "48.7395768", lon: str = "19.1376321", **extra) -> dict:
    return {"category": category, "type": kind, "addresstype": extra.pop("addresstype", kind), "lat": lat, "lon": lon,
            "osm_type": "way", "osm_id": 61153499,
            "address": {"road": "Cesta na amfiteáter", "house_number": "2728/1", "city": town, **extra}}


def run(answers: dict, place: str, town: str = "Banská Bystrica"):
    asked = []

    def search(query: str) -> list:
        asked.append(query)
        return answers.get(query, [])

    row, note = geocode_venues.geocode(town, place, search, lambda: None)
    return row, note, asked


def test_a_room_text_is_placed_by_the_address_it_holds():
    place = "CPDV UMB, Cesta na amfiteáter 1 (nová budova EF UMB), učebňa č. 507"
    answers = {"Cesta na amfiteáter 1, Banská Bystrica": [hit("building", "university", "Banská Bystrica")]}
    row, _note, asked = run(answers, place)
    assert asked == ["CPDV UMB, Cesta na amfiteáter 1, učebňa č. 507, Banská Bystrica", "Cesta na amfiteáter 1, Banská Bystrica"]
    assert row["match"] == "cpdv umb cesta na amfiteáter 1 učebňa č. 507"
    assert (row["town"], row["lat"], row["lon"], row["osm"]) == ("banska-bystrica", "48.7395768", "19.1376321", "way/61153499")
    assert row["streetAddress"] == "Cesta na amfiteáter 2728/1" and row["checked_by"] == "nominatim"


def test_a_town_a_street_or_a_district_is_no_venue():
    for answer in (hit("place", "town", "Banská Bystrica"), hit("boundary", "administrative", "Banská Bystrica"),
                   hit("highway", "residential", "Banská Bystrica"), hit("place", "suburb", "Banská Bystrica"),
                   hit("amenity", "theatre", "Banská Bystrica", addresstype="city")):
        row, note, _ = run({"Javorina, Banská Bystrica": [answer]}, "Javorina")
        assert row is None and "no venue" in note


def test_a_venue_of_the_same_name_in_another_town_or_outside_slovakia_is_refused():
    row, note, _ = run({"Kino, Zvolen": [hit("amenity", "cinema", "Detva")]}, "Kino", "Zvolen")
    assert row is None and note == "in Detva, not in Zvolen"
    row, note, _ = run({"Kino, Zvolen": [hit("amenity", "cinema", "Zvolen", lat="50.1")]}, "Kino", "Zvolen")
    assert row is None and note == "outside Slovakia"


def test_the_match_key_is_the_one_the_pipelines_compute():
    # pipelines/common.yaml: lower case, parentheses dropped, commas and semicolons as spaces.
    assert geocode_venues.key("Veľká zasadačka a veľký študijný hub, Tajovského 40 (SĎ 1)") == "veľká zasadačka a veľký študijný hub tajovského 40"
    assert 'replace_all("\\\\([^)]*\\\\)", " ").re_replace_all("[,;]", " ")' in (EVENTS / "pipelines/common.yaml").read_text()


def test_every_venue_row_names_its_osm_object_and_who_checked_it():
    rows = list(csv.DictReader((EVENTS / "venues.csv").open(encoding="utf-8")))
    assert rows and all(r["checked_by"] in ("hand", "nominatim") for r in rows)
    assert all(r["osm"].split("/")[0] in ("node", "way", "relation") and r["osm"].split("/")[1].isdigit() for r in rows)
    keys = [(r["town"], r["match"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        assert 47.7 <= float(r["lat"]) <= 49.7 and 16.8 <= float(r["lon"]) <= 22.6, r
