"""The city's open registers in the Helsinki space (T-2787, PL-03, DM-01, DM-61).

Bento runs each committed mapping over a recorded answer of the URL its DataSource declares,
fetched on 2026-09-25 and trimmed to a few records (`fixtures/helsinki/open-data/`), and every
entity it writes is checked against the space's generated JSON Schema: the model is what the
gateway enforces, so an entity the schema refuses is a write the gateway would refuse. The edge
cases are those same answers edited in the one place they name, never an invented feed.

Without a container runtime the Bento cases skip; the seed cases do not.
"""

import copy
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-helsinki-open-data")

ROOT = Path(__file__).resolve().parent.parent
HELSINKI = ROOT / "components/context-gateway/seed/helsinki"
FIXTURES = Path(__file__).resolve().parent / "fixtures/helsinki/open-data"

# pipeline -> (fixture, the type it writes, how many entities the recording holds)
FEEDS = {
    "services": ("servicemap-units.json", "PointOfInterest", 5),
    "beach-water": ("uiras-beaches.json", "WaterQualityObserved", 3),
    "parking-areas": ("parking-areas.json", "ParkingArea", 3),
    # Three areas, two of them one application: two permits.
    "excavation": ("excavation.json", "PublicAreaPermit", 2),
    "traffic-arrangements": ("traffic-arrangements.json", "PublicAreaPermit", 2),
    "area-events": ("area-events.json", "PublicAreaPermit", 3),
    # Two features, one of them the territorial sea, which has no district number.
    "districts": ("districts.json", "CityDistrict", 1),
    "subdistricts": ("subdistricts.json", "CityDistrict", 2),
    "fee-parking-zones": ("payment-zones.json", "ParkingZone", 1),
    "resident-parking-zones": ("resident-zones.json", "ParkingZone", 2),
}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def run(pipeline: str, document: dict) -> list[dict]:
    return open_data.run(HELSINKI / f"helsinki-pipeline-{pipeline}-bento.yaml", json.dumps(document).encode(), "helsinki")


def schema_errors(entity: dict) -> list[str]:
    return open_data.schema_errors(HELSINKI / "helsinki.v1.schema.json", entity)


@pytest.fixture(scope="module")
def written():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(name, fixture(recording)) for name, (recording, _, _) in FEEDS.items()}


@requires_docker
def test_every_feed_writes_its_one_type_and_every_record_it_can(written):
    for name, (_, kind, count) in FEEDS.items():
        assert {e["type"] for e in written[name]} == {kind}, name
        assert len(written[name]) == count, name


@requires_docker
def test_every_entity_is_one_the_gateway_accepts(written):
    for name, entities in written.items():
        for entity in entities:
            assert not schema_errors(entity), (name, entity["id"], schema_errors(entity))


@requires_docker
def test_every_id_is_the_four_segment_urn_of_the_space_and_unique(written):
    ids = [e["id"] for entities in written.values() for e in entities]
    assert len(ids) == len(set(ids))
    for entity in (e for entities in written.values() for e in entities):
        assert re.fullmatch(rf"urn:ngsi-ld:{entity['type']}:hel\.fi:helsinki:[A-Za-z0-9-]+", entity["id"]), entity["id"]


@requires_docker
def test_every_entity_credits_its_publisher_and_its_source(written):
    for entities in written.values():
        for entity in entities:
            assert entity["dataProvider"]["value"], entity["id"]
            assert entity["source"]["value"].startswith("https://"), entity["id"]


@requires_docker
def test_the_areas_of_one_application_are_one_permit_with_every_outline(written):
    areas = fixture("excavation.json")["features"]
    numbers = [a["properties"]["hakemustunnus"] for a in areas]
    shared = next(n for n in numbers if numbers.count(n) == 2)
    permit = next(e for e in written["excavation"] if e["permitNumber"]["value"] == shared)
    assert permit["id"] == f"urn:ngsi-ld:PublicAreaPermit:hel.fi:helsinki:{shared}"
    assert permit["location"]["value"]["type"] == "MultiPolygon"
    assert len(permit["location"]["value"]["coordinates"]) == 2
    # "34 PAKILA" names district 34, which the districts pipeline writes as district-34.
    district = next(a for a in areas if a["properties"]["hakemustunnus"] == shared)["properties"]["kaupunginosa"]
    number = int(district.split()[0])
    assert permit["refDistrict"] == {
        "type": "Relationship", "object": f"urn:ngsi-ld:CityDistrict:hel.fi:helsinki:district-{number}",
    }


@requires_docker
def test_an_event_without_build_dates_is_covered_by_its_own_days(written):
    events = {e["permitNumber"]["value"]: e for e in written["area-events"]}
    for area in fixture("area-events.json")["features"]:
        props = area["properties"]
        permit = events[props["hakemustunnus"]]
        expected = props["rakentaminen_alkaa"] if re.fullmatch(r"\d{4}-\d\d-\d\d", str(props["rakentaminen_alkaa"])) else props["tapahtuma_alkaa"]
        assert permit["permitStart"]["value"] == expected


@requires_docker
def test_no_permit_carries_its_applicant_or_contractor_even_when_the_register_fills_them():
    recording = fixture("excavation.json")
    for area in recording["features"]:
        area["properties"]["hakija"] = "Applicant Person"
        area["properties"]["tyon_suorittaja"] = "Contractor Person"
    for permit in run("excavation", recording):
        assert "Person" not in json.dumps(permit)


@requires_docker
def test_a_permit_the_register_gives_no_status_or_no_dates_is_dropped():
    recording = fixture("area-events.json")
    first, second = recording["features"][0], recording["features"][1]
    first["properties"]["status"] = "Peruttu"
    second["properties"]["tapahtuma_alkaa"] = "None"
    second["properties"]["rakentaminen_alkaa"] = "None"
    kept = {e["permitNumber"]["value"] for e in run("area-events", recording)}
    assert first["properties"]["hakemustunnus"] not in kept
    assert second["properties"]["hakemustunnus"] not in kept
    assert len(kept) == 1


@requires_docker
def test_a_unit_writes_its_opening_hours_and_never_its_contact_person():
    recording = fixture("servicemap-units.json")
    library = recording["results"][0]
    library["connections"].append({
        "section_type": "PHONE_OR_EMAIL", "name": {"fi": "Asiakaspalvelu"},
        "phone": "+358 9 000 0000", "email": "someone@example.test", "contact_person": "Staff Member",
    })
    entity = next(e for e in run("services", recording) if e["id"].endswith(f"servicemap-{library['id']}"))
    assert entity["serviceCategory"]["value"] == "library"
    assert entity["openingHours"]["languageMap"]["fi"].startswith("Normaaliaukioloaika")
    text = json.dumps(entity)
    assert "Staff Member" not in text and "someone@example.test" not in text and "+358" not in text


@requires_docker
def test_a_unit_of_no_service_this_space_keeps_is_not_written():
    recording = fixture("servicemap-units.json")
    recording["results"][0]["services"] = [9999]
    assert len(run("services", recording)) == 4


@requires_docker
def test_a_beach_sensor_without_a_reading_has_no_temperature_and_points_at_its_beach(written):
    silent = [e for e in written["beach-water"] if "temperature" not in e]
    assert len(silent) == 1 and "dateObserved" not in silent[0]
    reading = next(e for e in written["beach-water"] if "temperature" in e)
    assert reading["temperature"]["unitCode"] == "CEL"
    assert reading["temperature"]["observedAt"].endswith("Z")
    assert reading["refPointOfInterest"]["object"].startswith("urn:ngsi-ld:PointOfInterest:hel.fi:helsinki:servicemap-")


@requires_docker
def test_a_parking_area_the_city_has_not_estimated_has_no_capacity_rather_than_zero(written):
    assert sorted("totalSpotNumber" in e for e in written["parking-areas"]) == [False, True, True]


@requires_docker
def test_districts_read_as_a_person_writes_them_and_sub_districts_keep_the_statistics_code(written):
    district = written["districts"][0]
    assert district["name"]["languageMap"] == {"fi": "Villinki", "sv": "Villinge"}
    assert district["id"].endswith(":district-50")
    codes = {e["districtCode"]["value"] for e in written["subdistricts"]}
    assert all(re.fullmatch(r"091\d{7}", code) for code in codes)
    assert all(e["id"].endswith("subdistrict-" + e["districtCode"]["value"]) for e in written["subdistricts"])


@requires_docker
def test_a_zone_link_without_a_scheme_is_written_as_https(written):
    fee = written["fee-parking-zones"][0]
    assert fee["zoneKind"]["value"] == "fee" and fee["zoneCode"]["value"] == "1"
    assert fee["url"]["value"] == "https://www.hel.fi/pysakointi"
    assert "4 euroa tunnilta" in fee["description"]["languageMap"]["fi"]


@requires_docker
def test_an_empty_answer_writes_nothing():
    for name, (recording, _, _) in FEEDS.items():
        empty = copy.deepcopy(fixture(recording))
        empty["results" if "results" in empty else "features"] = []
        assert run(name, empty) == [], name


def test_a_value_outside_the_model_is_refused_by_the_schema():
    permit = {
        "id": "urn:ngsi-ld:PublicAreaPermit:hel.fi:helsinki:KP2602482",
        "type": "PublicAreaPermit",
        "permitKind": {"type": "Property", "value": "excavation"},
        "permitNumber": {"type": "Property", "value": "KP2602482"},
        "permitStatus": {"type": "Property", "value": "cancelled"},
        "permitStart": {"type": "Property", "value": "2026-09-14"},
        "permitEnd": {"type": "Property", "value": "2026-09-17"},
    }
    assert any("cancelled" in message for message in schema_errors(permit))
    permit["permitStatus"]["value"] = "ongoing"
    assert not schema_errors(permit)
    permit["applicant"] = {"type": "Property", "value": "somebody"}
    assert any("applicant" in message for message in schema_errors(permit))


def test_every_feed_is_seeded_as_a_datasource_a_pipeline_and_a_mapping():
    index = yaml.safe_load((HELSINKI / "index.yaml").read_text())
    model = yaml.safe_load((HELSINKI / "helsinki-datamodel.yaml").read_text())
    public = yaml.safe_load((HELSINKI / "helsinki-policy-public-all.yaml").read_text())
    readable = {e["type"] for rule in public["spec"]["information"] for e in rule["entities"]}
    for name, (_, kind, _) in FEEDS.items():
        pipeline = yaml.safe_load((HELSINKI / f"helsinki-pipeline-{name}.yaml").read_text())
        datasource = yaml.safe_load((HELSINKI / f"helsinki-datasource-{name}.yaml").read_text())
        assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == datasource["metadata"]["name"]
        assert pipeline["spec"]["output"]["type"] == kind
        # The domain is the organization's, rendered when the repository is loaded (CC-74).
        assert pipeline["spec"]["targetEndpoint"] == "urn:ngsi-ld:Endpoint:{orgDomain}:helsinki:helsinki-all"
        # Every pipeline states what it may use on the one node (Development/12 §4).
        assert pipeline["spec"]["quotas"]["maxMemoryMb"] <= 256
        assert datasource["spec"]["http"]["url"].startswith("https://")
        assert kind in model["spec"]["classes"]
        assert kind in readable, f"{kind} is not readable through the public endpoint"
        for seeded in (f"helsinki-datasource-{name}.yaml", f"helsinki-pipeline-{name}.yaml",
                       f"helsinki-pipeline-{name}-bento.yaml"):
            assert seeded in index, seeded
        assert index[f"helsinki-pipeline-{name}-bento.yaml"] == f"projects/helsinki/pipelines/{name}/bento.yaml"


def test_every_wfs_feed_asks_for_wgs84():
    for name in FEEDS:
        url = yaml.safe_load((HELSINKI / f"helsinki-datasource-{name}.yaml").read_text())["spec"]["http"]["url"]
        if "kartta.hel.fi" in url:
            # The layers' own system is EPSG:3879; a GeoProperty is WGS84 (CIM 009).
            assert "srsName=EPSG:4326" in url, name


def test_the_model_classes_and_the_manifest_agree():
    linkml = yaml.safe_load((HELSINKI / "helsinki.linkml.yaml").read_text())
    manifest = yaml.safe_load((HELSINKI / "helsinki-datamodel.yaml").read_text())
    assert set(manifest["spec"]["classes"]) == set(linkml["classes"])
