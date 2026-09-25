"""Prague's open data in project `praha` (T-2785, PL-03, DM-01, DM-61, PF-84).

Bento runs each committed mapping over a recorded answer of the URL its DataSource declares,
fetched on 2026-09-25 and trimmed to a few records (`fixtures/praha/`), and every entity it writes
is checked against the space's generated JSON Schema, which the gateway enforces. The edge cases
are those same answers edited in the one place they name, never an invented feed.

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

pytestmark = pytest.mark.xdist_group("docker-praha-open-data")

ROOT = Path(__file__).resolve().parent.parent
PRAHA = ROOT / "components/context-gateway/seed/praha"
FIXTURES = Path(__file__).resolve().parent / "fixtures/praha"
SPACE = "praha-mesto"

# pipeline -> (fixture, the type it writes, how many entities the recording holds)
FEEDS = {
    "bike-stations": ("bike-stations.json", "BikeHireDockingStation", 3),
    "bike-availability": ("bike-availability.json", "BikeHireDockingStation", 4),
    # Six rows: four registrations of Libuš, one of Legerova, one station elsewhere in the country.
    "air-quality": ("air-quality.csv", "AirQualityObserved", 2),
    "districts": ("districts.json", "CityDistrict", 2),
    "schools": ("schools.json", "PointOfInterest", 3),
    "culture": ("culture.json", "PointOfInterest", 2),
    "toilets": ("toilets.json", "PointOfInterest", 2),
    "waste-stations": ("waste-stations.json", "WasteContainerIsle", 2),
    "park-and-ride": ("park-and-ride.json", "OffStreetParking", 2),
    "ticket-points": ("ticket-points.json", "PointOfInterest", 3),
    # Three lines, one of them a correction the city files under no area.
    "budget": ("budget.json", "BudgetLine", 3),
    # Golemio (T-2907). Three car parks, one of them (TSK's b567b2eb) paired with no IPR record.
    "park-and-ride-occupancy": ("golemio-park-and-ride.json", "OffStreetParking", 2),
    # Two collection points, twelve containers, four of them monitored.
    "waste-fill": ("golemio-waste-containers.json", "WasteContainer", 4),
}

# Feeds that only add live attributes to an entity another feed writes: its credit is that feed's,
# and the gateway's upsert merges, so writing a second credit would overwrite the first.
MERGED = {"park-and-ride-occupancy"}


def recorded(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def run(pipeline: str, document: bytes) -> list[dict]:
    return open_data.run(PRAHA / f"praha-pipeline-{pipeline}-bento.yaml", document, SPACE)


def schema_errors(entity: dict) -> list[str]:
    return open_data.schema_errors(PRAHA / "praha.v1.schema.json", entity)


def edited(name: str, edit) -> bytes:
    document = json.loads(recorded(name).decode("utf-8-sig"))
    edit(document)
    return json.dumps(document).encode()


@pytest.fixture(scope="module")
def written():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(name, recorded(fixture)) for name, (fixture, _, _) in FEEDS.items()}


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
def test_every_id_is_the_four_segment_urn_of_the_space_and_unique_per_type(written):
    ids = {}
    for name, entities in written.items():
        for entity in entities:
            assert re.fullmatch(rf"urn:ngsi-ld:{entity['type']}:hel\.fi:{SPACE}:[a-z0-9-]+", entity["id"]), entity["id"]
            ids.setdefault(name, []).append(entity["id"])
    for name, own in ids.items():
        assert len(own) == len(set(own)), name


@requires_docker
def test_every_entity_credits_its_publisher_and_its_source(written):
    for name, entities in written.items():
        if name in MERGED:
            assert not any("dataProvider" in e or "source" in e for e in entities), name
            continue
        for entity in entities:
            assert entity["dataProvider"]["value"], entity["id"]
            assert entity["source"]["value"].startswith("https://"), entity["id"]
    ipr = [e for name in ("districts", "schools", "culture", "toilets", "waste-stations", "park-and-ride") for e in written[name]]
    # IPR's licence asks for this credit, word for word.
    assert all("datový podklad © IPR Praha" in e["dataProvider"]["value"] for e in ipr)


@requires_docker
def test_the_station_and_its_availability_are_one_entity(written):
    stations = {e["id"] for e in written["bike-stations"]}
    status = {e["id"]: e for e in written["bike-availability"]}
    assert stations <= set(status)
    # The fourth station of the recording neither rents nor takes back bikes.
    assert sorted(e["status"]["value"] for e in status.values()) == ["outOfService", "working", "working", "working"]
    assert all(e["dateModified"]["value"].endswith("Z") for e in status.values())


@requires_docker
def test_air_quality_keeps_prague_and_drops_a_missing_hour(written):
    libus = next(e for e in written["air-quality"] if e["id"].endswith(":chmi-alib"))
    assert {k for k in libus if k in ("pm10", "pm25", "no2", "o3", "so2", "co")} == {"pm10", "pm25", "no2", "o3"}
    assert libus["pm10"] == {"type": "Property", "value": 4.9, "unitCode": "GQ", "observedAt": "2026-09-25T03:00:00Z"}
    # Registration 10221 is outside Prague and wrote -5003, ČHMÚ's missing value; neither lands.
    assert "-5003" not in json.dumps(written["air-quality"])


@requires_docker
def test_a_negative_reading_is_never_written_as_a_value():
    text = recorded("air-quality.csv").decode().replace("40285, 2026-09-25T03:00:00Z, 8, 4.9", "40285, 2026-09-25T03:00:00Z, 6, -5003.0")
    libus = next(e for e in run("air-quality", text.encode()) if e["id"].endswith(":chmi-alib"))
    assert "pm10" not in libus and libus["pm25"]["value"] == 3.8


@requires_docker
def test_a_collection_point_points_at_its_district_by_ruian_code(written):
    point = written["waste-stations"][0]
    assert point["refDistrict"]["object"] == f"urn:ngsi-ld:CityDistrict:hel.fi:{SPACE}:district-538931"
    assert point["accessRestriction"]["value"] == "public"
    assert all(re.fullmatch(r"\d{6}", e["districtCode"]["value"]) for e in written["districts"])
    assert all(e["id"].endswith("district-" + e["districtCode"]["value"]) for e in written["districts"])


@requires_docker
def test_an_unknown_access_word_is_left_out_rather_than_guessed():
    def edit(d):
        d["features"][0]["properties"]["pristup"] = "po dohodě"
    first = run("waste-stations", edited("waste-stations.json", edit))[0]
    assert "accessRestriction" not in first and not schema_errors(first)


@requires_docker
def test_ids_follow_the_layer_globalid_not_its_objectid():
    def edit(d):
        d["features"][0]["properties"]["objectid"] = 999999
    again = run("schools", edited("schools.json", edit))
    assert [e["id"] for e in again] == [e["id"] for e in run("schools", recorded("schools.json"))]


@requires_docker
def test_a_row_without_a_name_or_a_key_is_dropped():
    def edit(d):
        d["features"][0]["properties"]["nazev_zar"] = "  "
        d["features"][1]["properties"]["globalid"] = None
    assert len(run("culture", edited("culture.json", edit))) == 0


@requires_docker
def test_ticket_point_hours_read_as_day_ranges(written):
    hours = {e["id"].rsplit(":", 1)[1]: e["openingHours"]["languageMap"]["cs"] for e in written["ticket-points"]}
    assert hours["pid-dp2"] == "po–ne 5:00-24:00"
    assert hours["pid-cd551069"] == "po–so 05:50-19:05\nne 06:50-19:05"


@requires_docker
def test_budget_codes_keep_their_padding_and_the_byte_order_mark_is_read(written):
    lines = {e["id"].rsplit(":", 1)[1]: e for e in written["budget"]}
    school = lines["mhmp-2026-09-003122-6121-000000000"]
    assert school["budgetArea"]["value"] == "09 Školství"
    assert school["budgetFunction"]["value"] == "003122 Střední odborné školy"
    assert school["approvedAmount"]["value"] == 1700 and school["adjustedAmount"]["value"] == 102413.6
    correction = lines["mhmp-2026-00-000000-0000-000000000"]
    assert "budgetArea" not in correction and correction["adjustedAmount"]["value"] == -0.03
    assert recorded("budget.json").startswith(b"\xef\xbb\xbf")


@requires_docker
def test_a_budget_line_with_an_amount_that_is_not_a_number_is_dropped():
    def edit(d):
        d["data"]["row"][0]["rozpocet_upraveny"] = "n/a"
    assert len(run("budget", edited("budget.json", edit))) == 2


@requires_docker
def test_an_empty_answer_writes_nothing():
    assert run("air-quality", recorded("air-quality.csv").splitlines()[0] + b"\n") == []
    assert run("ticket-points", b"[]") == []
    assert run("budget", b'{"data": {"row": []}}') == []
    for name in ("bike-stations", "bike-availability"):
        assert run(name, b'{"data": {"stations": []}}') == []
    for name in ("districts", "schools", "culture", "toilets", "waste-stations", "park-and-ride", "waste-fill"):
        assert run(name, b'{"type": "FeatureCollection", "features": []}') == [], name
    assert run("park-and-ride-occupancy", b"[]") == []


def test_a_value_outside_the_model_is_refused_by_the_schema():
    station = {
        "id": f"urn:ngsi-ld:BikeHireDockingStation:hel.fi:{SPACE}:nextbike-1",
        "type": "BikeHireDockingStation",
        "status": {"type": "Property", "value": "closed"},
    }
    assert any("closed" in message for message in schema_errors(station))
    station["status"]["value"] = "working"
    assert not schema_errors(station)
    station["availableBikeNumber"] = {"type": "Property", "value": -1}
    assert schema_errors(station)


@requires_docker
def test_occupancy_lands_on_the_ids_ipr_writes_and_an_unpaired_car_park_is_left_out(written):
    ids = {e["id"].rsplit(":", 1)[1] for e in written["park-and-ride-occupancy"]}
    # Skalka II and Kotlářka, by the globalid the park-and-ride pipeline keys them on.
    assert ids == {"ipr-a7c9a9af-a0fb-4005-8baf-c9a202b763ad", "ipr-8e869f78-c4e5-41fc-a316-ccff35083fdc"}
    skalka = next(e for e in written["park-and-ride-occupancy"] if e["id"].endswith("a7c9a9af-a0fb-4005-8baf-c9a202b763ad"))
    assert skalka["availableSpotNumber"]["value"] == 23 and skalka["occupiedSpotNumber"]["value"] == 55
    assert skalka["dateModified"]["value"] == "2026-09-25T13:34:01Z"
    # The capacity, the name and the outline are IPR's; the live feed never writes them.
    assert not any(k in e for e in written["park-and-ride-occupancy"] for k in ("totalSpotNumber", "name", "location"))


@requires_docker
def test_a_count_that_is_not_a_whole_number_is_left_out_and_a_car_park_without_one_is_not_written():
    def edit(d):
        d[0]["free_spot_number"] = -3
        d[0]["occupied_spot_number"] = 12.5
        d[1]["free_spot_number"] = None
        d[1]["occupied_spot_number"] = "n/a"
        d[1]["last_updated"] = None
    answer = run("park-and-ride-occupancy", edited("golemio-park-and-ride.json", edit))
    assert [set(e) - {"id", "type"} for e in answer] == [{"dateModified"}]
    assert not schema_errors(answer[0])


@requires_docker
def test_a_monitored_container_points_at_the_collection_point_the_ipr_feed_writes(written):
    isles = {e["stationCode"]["value"]: e["id"] for e in written["waste-stations"]}
    containers = written["waste-fill"]
    assert {c["refWasteContainerIsle"]["object"] for c in containers if "0022-001" in c["refWasteContainerIsle"]["object"]} == {isles["0022/ 001"]}
    metal = next(c for c in containers if c["id"].endswith(":ksnko-2"))
    assert metal["wasteKind"]["value"] == "metal" and metal["fillingLevel"]["value"] == 0.48
    assert metal["containerCode"]["value"] == "2" and metal["dateModified"]["value"] == "2026-09-25T10:35:39Z"


@requires_docker
def test_an_unmonitored_or_unknown_container_is_not_written_and_a_missing_reading_writes_no_level():
    def edit(d):
        monitored = [c for c in d["features"][0]["properties"]["containers"] if c["is_monitored"]]
        monitored[0]["trash_type"] = {"id": 0, "description": "neznámý"}
        monitored[1]["last_measurement"]["percent_calculated"] = None
        monitored[2]["last_measurement"]["percent_calculated"] = 140
    answer = run("waste-fill", edited("golemio-waste-containers.json", edit))
    assert len(answer) == 3
    assert sum("fillingLevel" in c for c in answer) == 1
    assert all(not schema_errors(c) for c in answer)


@requires_docker
def test_the_two_spellings_of_a_register_number_are_two_collection_points():
    def edit(d):
        d["features"][1]["properties"]["stationnumber"] = d["features"][0]["properties"]["stationnumber"].replace("/ ", "/-")
    ids = [e["id"].rsplit(":", 1)[1] for e in run("waste-stations", edited("waste-stations.json", edit))]
    # `0022/ 001` and `0022/-001` are two points of the register (791 such pairs on 2026-09-25).
    assert ids == ["station-0022-001", "station-0022--001"]


def test_the_golemio_key_is_named_by_reference_and_committed_only_encrypted():
    index = yaml.safe_load((PRAHA / "index.yaml").read_text())
    for name in ("park-and-ride-occupancy", "waste-fill"):
        http = yaml.safe_load((PRAHA / f"praha-datasource-{name}.yaml").read_text())["spec"]["http"]
        assert http["authorization"] == {"header": "X-Access-Token", "headerRef": {"name": "golemio", "key": "token"}}
        assert not any(h.lower() in ("x-access-token", "authorization") for h in http["headers"])
        assert http["url"].startswith("https://api.golemio.cz/") and "token" not in http["url"].lower()
    secret = yaml.safe_load((PRAHA / "praha-secrets-golemio.enc.yaml").read_text())
    assert index["praha-secrets-golemio.enc.yaml"] == "projects/praha/secrets/golemio.enc.yaml"
    # Every value encrypted, the file sealed by its MAC, to an age recipient (CC-06, Architecture/06 §1.4).
    assert set(secret) == {"golemio", "sops"} and set(secret["golemio"]) == {"token"}
    assert re.fullmatch(r"ENC\[AES256_GCM,data:[^,]+,iv:[^,]+,tag:[^,]+,type:str\]", secret["golemio"]["token"])
    assert secret["sops"]["mac"].startswith("ENC[AES256_GCM,")
    assert [a["recipient"] for a in secret["sops"]["age"]] and all(a["recipient"].startswith("age1") for a in secret["sops"]["age"])


def test_every_feed_is_seeded_as_a_datasource_a_pipeline_and_a_mapping():
    index = yaml.safe_load((PRAHA / "index.yaml").read_text())
    model = yaml.safe_load((PRAHA / "praha-datamodel.yaml").read_text())
    public = yaml.safe_load((PRAHA / "praha-policy-public-read.yaml").read_text())
    readable = {e["type"] for rule in public["spec"]["information"] for e in rule["entities"]}
    for name, (_, kind, _) in FEEDS.items():
        pipeline = yaml.safe_load((PRAHA / f"praha-pipeline-{name}.yaml").read_text())
        datasource = yaml.safe_load((PRAHA / f"praha-datasource-{name}.yaml").read_text())
        assert pipeline["spec"]["source"]["dataSourceRef"]["name"] == datasource["metadata"]["name"]
        assert pipeline["spec"]["output"]["type"] == kind
        assert pipeline["spec"]["targetEndpoint"] == "urn:ngsi-ld:Endpoint:{orgDomain}:praha-mesto:praha-mesto"
        assert pipeline["spec"]["quotas"]["maxMemoryMb"] <= 256
        assert datasource["spec"]["http"]["url"].startswith("https://")
        assert kind in model["spec"]["classes"] and kind in readable
        for seeded in (f"praha-datasource-{name}.yaml", f"praha-pipeline-{name}.yaml", f"praha-pipeline-{name}-bento.yaml"):
            assert seeded in index, seeded


def test_every_pipeline_is_scheduled_and_the_project_has_room_for_a_hundred_more():
    """T-2873: the praha pipelines were refused on dev by a resident quota of one."""
    project = yaml.safe_load((PRAHA / "praha-project.yaml").read_text())
    assert project["spec"]["quotas"]["residentPipelines"] >= 100
    for name in FEEDS:
        period = yaml.safe_load((PRAHA / f"praha-pipeline-{name}.yaml").read_text())["spec"]["period"]
        seconds = int(period[:-1]) * {"s": 1, "m": 60, "h": 3600}[period[-1]]
        # PL-26: 30 s or longer is scheduled.
        assert seconds >= 300, name


def test_the_seed_index_lists_every_file_beside_it_and_the_forge_seeds_it():
    index = yaml.safe_load((PRAHA / "index.yaml").read_text())
    assert set(index) == {p.name for p in PRAHA.iterdir()} - {"index.yaml"}
    assert all(path.startswith("projects/praha/") for path in index.values())
    bootstrap = (ROOT / "components/gitea/values/bootstrap/development-values.yaml.gotmpl").read_text()
    assert 'context-gateway/seed/praha/index.yaml' in bootstrap


def test_the_space_is_public_and_published_with_the_licence_of_its_most_demanding_source():
    endpoint = yaml.safe_load((PRAHA / "praha-endpoint-mesto.yaml").read_text())
    space = yaml.safe_load((PRAHA / "praha-space-mesto.yaml").read_text())
    assert endpoint["spec"]["audience"] == "public"
    assert endpoint["spec"]["publish"]["ckan"]["license"] == "cc-by"
    assert endpoint["spec"]["publish"]["ckan"]["instanceRef"]["name"] == "praha"
    assert space["spec"]["urnSegment"] == SPACE
    for publisher in ("nextbike", "ČHMÚ", "IPR Praha", "ROPID"):
        assert publisher in space["metadata"]["description"]["en"]


def test_the_model_classes_and_the_manifest_agree():
    linkml = yaml.safe_load((PRAHA / "praha.linkml.yaml").read_text())
    manifest = yaml.safe_load((PRAHA / "praha-datamodel.yaml").read_text())
    assert set(manifest["spec"]["classes"]) == set(linkml["classes"])
