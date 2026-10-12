"""T-3949: `address` is a Smart Data Models PostalAddress, built from the source's own fields.

Each pipeline that writes an address runs in Bento over its recording (or, for the two feeds
without one, the smallest document of the source's shape) and every entity is checked against
the space's generated schema. A field the source leaves out stays out; a line of text is never
split into parts.
"""

import copy
import json
from pathlib import Path

import pytest

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-helsinki-open-data")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
FIXTURES = Path(__file__).resolve().parent / "fixtures/helsinki/open-data"


def run(pipeline: str, document: dict) -> list[dict]:
    return open_data.run_all(HELSINKI / f"helsinki-pipeline-{pipeline}-bento.yaml", json.dumps(document).encode(), "helsinki")


def accepted(entities: list[dict]) -> list[dict]:
    for entity in entities:
        errors = open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity)
        assert not errors, (entity["id"], errors)
    return entities


def address(entity: dict) -> dict | None:
    return entity.get("address", {}).get("value")


@requires_docker
def test_a_service_address_is_the_registers_fields_and_a_missing_one_stays_out():
    document = json.loads((FIXTURES / "servicemap-units.json").read_text())
    first = document["results"][0]
    with_city = copy.deepcopy(first)
    with_city.update(id=999001, address_city={"fi": "Helsinki", "sv": "Helsingfors"})
    without_street = copy.deepcopy(first)
    without_street.update(id=999002, street_address=None)
    document["results"] = [first, with_city, without_street]
    written = {e["id"].rsplit("-", 1)[1]: e for e in accepted(run("services", document))}
    assert address(written[str(first["id"])]) == {
        "streetAddress": first["street_address"]["fi"], "postalCode": first["address_zip"], "addressCountry": "FI",
    }
    assert address(written["999001"])["addressLocality"] == "Helsinki"
    assert "address" not in written["999002"]


@requires_docker
@pytest.mark.parametrize("pipeline, recording", [
    ("excavation", "excavation.json"),
    ("traffic-arrangements", "traffic-arrangements.json"),
    ("area-events", "area-events.json"),
])
def test_a_permit_keeps_its_address_line_whole(pipeline, recording):
    document = json.loads((FIXTURES / recording).read_text())
    # The line as the register has it, trimmed the way the pipeline trims every text.
    lines = {f["properties"]["hakemustunnus"]: (f["properties"].get("osoite") or "").strip() for f in document["features"]}
    for permit in accepted(run(pipeline, document)):
        line = lines[permit["permitNumber"]["value"]]
        if line:
            assert address(permit) == {"streetAddress": line, "addressLocality": "Helsinki", "addressCountry": "FI"}
        else:
            assert "address" not in permit


EVENT = {
    "id": "helsinki:agtest01",
    "name": {"fi": "Konsertti"},
    "start_time": "2026-10-12T10:00:00Z",
    "end_time": "2026-10-12T12:00:00Z",
    "event_status": "EventScheduled",
    "location": {
        "position": {"type": "Point", "coordinates": [24.95, 60.17]},
        "street_address": {"fi": "Siltakatu 11", "sv": "Brogatan 11"},
        "postal_code": "00580",
        "address_locality": {"fi": "Helsinki", "sv": "Helsingfors"},
    },
}


@requires_docker
def test_an_event_address_is_its_places_street_postal_code_and_locality():
    bare = copy.deepcopy(EVENT)
    bare["id"] = "helsinki:agtest02"
    del bare["location"]["postal_code"], bare["location"]["address_locality"]
    no_street = copy.deepcopy(EVENT)
    no_street["id"] = "helsinki:agtest03"
    del no_street["location"]["street_address"]
    written = {e["id"].rsplit(":", 1)[1]: e for e in accepted(run("events", {"data": [EVENT, bare, no_street]}))}
    assert address(written["helsinki-agtest01"]) == {
        "streetAddress": "Siltakatu 11", "postalCode": "00580", "addressLocality": "Helsinki", "addressCountry": "FI",
    }
    assert address(written["helsinki-agtest02"]) == {"streetAddress": "Siltakatu 11", "addressCountry": "FI"}
    assert "address" not in written["helsinki-agtest03"]


@requires_docker
def test_a_traffic_alert_address_is_its_municipality():
    situation = {
        "geometry": {"type": "Point", "coordinates": [24.75, 60.2]},
        "properties": {
            "situationId": "GUID50001",
            "situationType": "ROAD_WORK",
            "releaseTime": "2026-10-12T08:00:00Z",
            "announcements": [{
                "title": "Tie 101, Espoo",
                "location": {"description": "Kehä I"},
                "locationDetails": {"roadAddressLocation": {"primaryPoint": {"municipality": "Espoo"}}},
                "timeAndDuration": {"startTime": "2026-10-12T08:00:00Z"},
            }],
        },
    }
    (alert,) = accepted(run("traffic-messages", {"features": [situation]}))
    assert address(alert) == {"addressLocality": "Espoo", "addressCountry": "FI"}
