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


def test_the_village_itself_or_a_map_board_named_like_it_is_no_venue():
    # T-5135: Nominatim answered "Ľubietová" with the cadastral community and "Hriňová" with a map board.
    for answer in (hit("place", "cadastral_community", "Ľubietová", name="Ľubietová"),
                   hit("information", "map", "Ľubietová", name="Ľubietová"),
                   hit("tourism", "museum", "Ľubietová", name="Ľubietová")):
        answer["name"] = answer["address"].pop("name")
        row, note, _ = run({"Ľubietová, Ľubietová": [answer]}, "Ľubietová", "Ľubietová")
        assert row is None and "no venue" in note, note


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
    assert rows and all(r["checked_by"] in ("hand", "nominatim", "overpass") for r in rows)
    assert all(r["osm"].split("/")[0] in ("node", "way", "relation") and r["osm"].split("/")[1].isdigit() for r in rows)
    keys = [(r["town"], r["match"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        assert 47.7 <= float(r["lat"]) <= 49.7 and 16.8 <= float(r["lon"]) <= 22.6, r


def test_a_venue_already_in_the_table_is_never_looked_up_again(tmp_path, monkeypatch, capsys):
    known = next(csv.DictReader((EVENTS / "venues.csv").open(encoding="utf-8")))
    places = tmp_path / "places.csv"
    places.write_text(f"town,place\n{known['addressLocality']},{known['match']}\n", encoding="utf-8")
    asked = []
    monkeypatch.setattr(geocode_venues, "fetch", lambda q: asked.append(q) or [])
    assert geocode_venues.main([str(places)]) == 0
    assert asked == [], "a cached venue costs no request"


# --- offices.py (T-5215): the municipality's office as its home, its one culture house as "Kultúrny dom" -------

ospec = importlib.util.spec_from_file_location("offices", EVENTS / "offices.py")
offices = importlib.util.module_from_spec(ospec)
ospec.loader.exec_module(offices)


def element(kind: str, amenity: str, name: str | None, lat: float = 48.3, lon: float = 17.6, n: int = 1) -> dict:
    tags = {"amenity": amenity, "addr:street": "Hlavná", "addr:housenumber": "1"}
    if name:
        tags["name"] = name
    return {"type": kind, "id": n, "lat": lat, "lon": lon, "tags": tags} if kind == "node" else \
        {"type": kind, "id": n, "center": {"lat": lat, "lon": lon}, "tags": tags}


def answer(*munis) -> dict:
    """An Overpass answer: per municipality its boundary (name, maybe web site), then its elements."""
    out = []
    for name, website, items in munis:
        tags = {"name": name, **({"website": website} if website else {})}
        out += [{"type": "relation", "id": 2, "tags": tags}, *items]
    return {"elements": out}


def source(town: str, region: str = "Trnavský kraj", org_type: str = "municipality") -> dict:
    return {"town": town, "region_name": region, "org_type": org_type, "events_url": f"https://{offices.generate.slug(town)}.sk/"}


def test_the_office_becomes_the_home_and_the_one_culture_house_the_kulturny_dom():
    asked = []
    found = answer(("Bíňovce", None, [element("node", "townhall", "Obecný úrad", n=10),
                                                 element("way", "community_centre", "Kultúrny dom", 48.31, 17.61, n=11)]))
    venues, homes = offices.plan([source("Bíňovce")], set(), set(), lambda q: asked.append(q) or found)
    assert len(asked) == 1 and "Bíňovce" in asked[0], "one Overpass request for every source"
    assert homes == [{"events_url": "https://binovce.sk/", "town": "binovce", "match": "obecný úrad bíňovce"}]
    office = next(v for v in venues if v["match"] == "obecný úrad bíňovce")
    assert (office["osm"], office["streetAddress"], office["checked_by"]) == ("node/10", "Hlavná 1", "overpass")
    hall = {v["match"]: v for v in venues if v["osm"] == "way/11"}
    assert {"kultúrny dom", "kultúrny dom bíňovce", "kd"} <= set(hall) and hall["kd"]["lat"] == "48.3100000"


def test_no_office_two_culture_houses_or_two_villages_of_one_name_give_no_point_unless_the_web_site_tells():
    found = answer(
        ("Hubice", None, [element("node", "community_centre", "KD", n=1), element("node", "community_centre", "Sála", n=2)]),
        ("Lehota", "https://www.lehota.sk", [element("node", "townhall", "Obecný úrad", n=3)]),
        ("Lehota", None, [element("node", "townhall", "Obecný úrad", n=4)]),
        ("Kostolná", None, [element("node", "townhall", "Obecný úrad", n=5)]),
        ("Kostolná", None, [element("node", "townhall", "Obecný úrad", n=9)]),
        ("Častá", None, [element("node", "townhall", "Obecný úrad", lat=40.0, n=6)]),
    )
    venues, homes = offices.plan([source("Hubice"), source("Lehota"), source("Kostolná"), source("Častá")], set(), set(),
                                 lambda q: found)
    # Hubice: no office and no single culture house; Kostolná: two of that name, no web site tells them apart;
    # Častá: its only office lies outside Slovakia's box. Never a village centre instead. Lehota: its web site
    # names the one.
    assert [h["town"] for h in homes] == ["lehota"] and [v["osm"] for v in venues] == ["node/3"]


def test_a_named_office_wins_over_another_townhall_and_a_source_with_a_home_is_skipped():
    found = answer(("Galanta", None, [element("node", "townhall", "Mestský úrad Galanta", n=7),
                                                 element("node", "townhall", "Hasičská zbrojnica", n=8)]))
    venues, homes = offices.plan([source("Galanta", org_type="town")], set(), set(), lambda q: found)
    assert homes[0]["match"] == "mestský úrad galanta" and venues[0]["osm"] == "node/7"
    known = {(v["town"], v["match"]) for v in venues}
    assert offices.plan([source("Galanta", org_type="town")], known, {"https://galanta.sk/"}, lambda q: found) == ([], [])


def test_a_building_named_as_the_towns_culture_house_counts_and_so_does_the_text_the_events_wrote():
    found = answer(("Žarnovica", None, [element("node", "townhall", "Mestský úrad", n=1),
                                        element("way", "", "Kultúrny dom Žarnovica", n=2),
                                        element("node", "community_centre", "Exercičný dom", n=3)]))
    found["elements"][2]["tags"].pop("amenity")
    venues, _ = offices.plan([source("Žarnovica", org_type="town")], set(), set(), lambda q: found,
                             {"Žarnovica": {"Kultúrny dom v Žarnovici", "Kino Baník"}})
    hall = {v["match"] for v in venues if v["osm"] == "way/2"}
    assert {"kultúrny dom", "kultúrny dom v žarnovici"} <= hall and "kino baník" not in hall


def test_a_culture_house_is_one_by_its_name_and_of_its_own_town():
    # Read on Overpass 2026-10-22: the single community_centre of these villages.
    cases = [("Kultúrny dom", "Babín", True), ("Kulturny dom", "Chocholná-Velčice", True),
             ("Mestské kultúrne stredisko v Revúcej", "Revúca", True), ("MSKS Šamorín - VMK Somorja", "Šamorín", True),
             ("Kultúrny dom Ponická Lehôtka", "Poniky", False), ("Exercičný dom", "Marianka", False),
             ("Kursalon", "Nimnica", False), ("Diecézne centrum mládeže Maják", "Špania Dolina", False)]
    for name, town, own in cases:
        assert offices.own_hall({"tags": {"name": name}}, town) is own, name
    assert offices.OFFICE.search("OcÚ Trstice") and not offices.OFFICE.search("Hasičská zbrojnica")
