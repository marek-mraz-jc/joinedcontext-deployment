"""T-4275: every type a seeded space declares states its history, off or kept for a while.

The owner's defaults (DM-82, ADR-N-046 2.3): a measurement series keeps 30 days of history, every
other type keeps its current state only; the seed never keeps a history forever. A space's model
is its whole list of types (DM-61), so a type without a rule would keep everything it is sent.
"""

import re
from collections import defaultdict
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "components/context-gateway/seed"
MEASURED = {
    "AirQualityObserved", "WeatherObserved", "WaterQualityObserved", "KeyPerformanceIndicator",
    "OffStreetParking", "ParkingArea", "BikeHireDockingStation",
}
DURATION = re.compile(r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?$")


def manifests():
    for path in SEED.rglob("*.yaml"):
        if path.name.endswith(".linkml.yaml"):
            continue
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and "kind" in doc:
                yield doc


def spaces() -> dict[str, tuple[dict, set[str]]]:
    classes, found = defaultdict(set), {}
    for doc in manifests():
        ns = doc["metadata"].get("namespace")
        if doc["kind"] == "DataModel":
            ref = doc["spec"].get("contextSpaceRef")
            classes[f"{ns}/{ref['name'] if isinstance(ref, dict) else ref}"] |= set(doc["spec"].get("classes") or [])
        elif doc["kind"] == "ContextSpace":
            found[f"{ns}/{doc['metadata']['name']}"] = doc["spec"]
    return {name: (spec, classes[name]) for name, spec in found.items()}


def test_every_declared_type_has_one_history_rule():
    for name, (spec, types) in spaces().items():
        rules = [rule["entityType"] for rule in spec.get("retention", [])]
        assert len(rules) == len(set(rules)), name
        assert set(rules) == types, f"{name}: {sorted(types ^ set(rules))}"


def test_a_history_is_off_or_a_duration_and_never_forever():
    for name, (spec, _) in spaces().items():
        for rule in spec.get("retention", []):
            history = rule.get("history")
            # a bare `off` is the boolean false to a YAML 1.1 reader: the seed quotes it
            assert history == "off" or (isinstance(history, str) and DURATION.match(history)), (name, rule)
            assert "reason" not in rule, (name, rule)


def test_measurements_keep_thirty_days_and_the_rest_keep_none():
    for name, (spec, _) in spaces().items():
        for rule in spec.get("retention", []):
            want = "P30D" if rule["entityType"] in MEASURED else "off"
            assert rule["history"] == want, (name, rule)


def test_the_duration_pattern_refuses_what_is_not_one():
    for bad in ["P", "PT", "30D", "P30", "forever", "P1DT", "off "]:
        assert not DURATION.match(bad), bad
    for good in ["P30D", "PT8H", "P1Y2M", "PT5M", "P2W"]:
        assert DURATION.match(good), good
