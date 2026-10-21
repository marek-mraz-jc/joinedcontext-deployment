"""T-3904: the helsinki space keeps its transport data under retention and quality rules.

The values are the owner's (DM-81, DM-86, ADR-N-046): a vehicle is gone five minutes after its
last report and keeps an hour of track, never more (owner, T-4624); positions lie in what
HSL's feeds cover, speeds up to 160 km/h (the Sm5 commuter trains), and no report is ahead of the clock. Beside the
vehicle only an Alert loses its current state, 30 days after its last write, as the net for a writer that sets no end
(T-4843); no other type of the seed does.
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


def test_a_vehicle_is_kept_five_minutes_after_its_last_report_and_an_hour_of_its_track():
    (vehicle,) = [rule for rule in helsinki()["retention"] if rule["entityType"] == "Vehicle"]
    assert {k: v for k, v in vehicle.items() if k != "attributes"} == {"entityType": "Vehicle", "current": "PT5M", "history": "PT1H"}
    # The three that say what a vehicle is, written without an observedAt, record a change (T-4844).
    assert set(vehicle["attributes"]) == {"fleetVehicleId", "transportMode", "vehicleType"}


def test_no_vehicle_of_any_space_keeps_more_than_an_hour_of_track():
    """The owner's order (T-4624) holds for every live vehicle feed, not only HSL's."""
    rules = [(name, rule.get("history")) for name, space in spaces().items()
             for rule in space["spec"].get("retention", []) if rule["entityType"] == "Vehicle"]
    assert rules and all(history in ("off", "PT1H", "PT30M", "PT5M") for _, history in rules), rules


def test_no_other_type_loses_its_current_state():
    losing = [(name, rule["entityType"]) for name, space in spaces().items()
              for rule in space["spec"].get("retention", []) if "current" in rule]
    assert sorted(losing) == [("helsinki/helsinki", "Alert"), ("helsinki/helsinki", "Vehicle")]
    (alert,) = [rule for rule in helsinki()["retention"] if rule["entityType"] == "Alert"]
    assert alert == {"entityType": "Alert", "current": "P30D", "history": "off"}


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


def test_bike_stations_record_a_change_and_an_hourly_heartbeat_and_no_slot_is_a_count():
    """T-4669 (ADR-N-054 2.2, DM-110): onChange fits levels only, never a quantity per interval."""
    (bikes,) = [rule for rule in helsinki()["retention"] if rule["entityType"] == "BikeHireDockingStation"]
    assert bikes == {"entityType": "BikeHireDockingStation", "history": "P30D", "record": "onChange", "heartbeat": "PT1H"}
    model = yaml.safe_load((HELSINKI / "helsinki.linkml.yaml").read_text())
    slots = model["classes"]["BikeHireDockingStation"]["slots"]
    counted = [slot for slot in slots
               if (model.get("slots", {}).get(slot) or {}).get("annotations", {}).get("quantity") == "perInterval"]
    assert counted == []
