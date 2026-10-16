"""T-3904: the helsinki space keeps its transport data under retention and quality rules.

The values are the owner's (DM-81, DM-86, ADR-N-046): a vehicle is gone five minutes after its
last report and its track is kept eight hours; positions lie in what HSL's feeds cover, speeds
up to 160 km/h (the Sm5 commuter trains), and no report is ahead of the clock. No other space
of the seed loses data.
"""

import csv
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
HELSINKI = SEED / "helsinki"
STOPS = Path(__file__).resolve().parent / "fixtures/helsinki/gtfs/stops.txt"


def spaces() -> dict[str, dict]:
    found = {}
    for path in SEED.rglob("*.yaml"):
        if path.name.endswith(".linkml.yaml"):
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == "ContextSpace":
                found[f"{doc['metadata']['namespace']}/{doc['metadata']['name']}"] = doc
    return found


def helsinki() -> dict:
    return spaces()["helsinki/helsinki"]["spec"]


def test_a_vehicle_is_kept_five_minutes_after_its_last_report_and_its_track_eight_hours():
    assert helsinki()["retention"] == [{"entityType": "Vehicle", "current": "PT5M", "history": "PT8H"}]


def test_no_other_space_declares_retention():
    keeping = [name for name, space in spaces().items() if space["spec"].get("retention")]
    # And the national air quality's week of history (T-4340, owner 2026-10-16).
    assert keeping == ["slovensko/ovzdusie-sk", "helsinki/helsinki"]


def test_each_rule_reads_a_slot_of_its_class_and_names_itself_once():
    model = yaml.safe_load((HELSINKI / "helsinki.linkml.yaml").read_text())
    rules = helsinki()["quality"]
    assert len({rule["name"] for rule in rules}) == len(rules)
    for rule in rules:
        assert rule["attribute"] in model["classes"][rule["entityType"]]["slots"] + ["location"], rule
    by_name = {rule["name"]: rule for rule in rules}
    assert by_name["vehicle-speed"] == {
        "name": "vehicle-speed", "entityType": "Vehicle", "kind": "range", "attribute": "speed", "min": 0, "max": 44.5,
    }
    assert by_name["vehicle-report-not-ahead"]["maxAhead"] == "PT30S"


def test_every_recorded_stop_lies_in_the_area():
    (area,) = [rule["bbox"] for rule in helsinki()["quality"] if rule["name"] == "stop-in-hsl-area"]
    min_lon, min_lat, max_lon, max_lat = area
    stops = [row for row in csv.DictReader(STOPS.open()) if row["stop_lat"].strip()]
    assert stops
    outside = [row["stop_name"] for row in stops
               if not (min_lon <= float(row["stop_lon"]) <= max_lon and min_lat <= float(row["stop_lat"]) <= max_lat)]
    assert outside == []
    # Rautatientori lies inside, Tampere does not: the box is HSL's, not Finland's.
    assert min_lon <= 24.94 <= max_lon and min_lat <= 60.17 <= max_lat
    assert not (min_lat <= 61.5 <= max_lat)
