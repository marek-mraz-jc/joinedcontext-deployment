"""Barcelona open data batch 2, environment (T-5263, PL-03, DM-01, DM-61): the hourly air quality.

Bento runs the committed mapping over `fixtures/barcelona/qualitat-aire-detall.csv`, Open Data
BCN's Qualitat_Aire_Detall.csv as the DataSource's URL answered it at 2026-10-22T19:43Z (its
newest hour 21:00 CEST = 19:00Z). Every entity is checked against the space's generated JSON
Schema, which the gateway enforces, and against the Smart Data Model at its vendored pin. The edge
cases are that recording edited in the one place each names.

Without a container runtime the Bento cases skip; the seed cases do not.
"""

import csv
import io
import os
import tempfile
import json
import shutil
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import requires_docker

pytestmark = pytest.mark.xdist_group("docker-barcelona-environment")

ROOT = Path(__file__).resolve().parent.parent
CITY = ROOT / "components/context-gateway/seed/barcelona"
MAPPING = CITY / "barcelona-pipeline-air-quality-bento.yaml"
RECORDED = (Path(__file__).resolve().parent / "fixtures/barcelona/qualitat-aire-detall.csv").read_text()
PREFIX = "urn:ngsi-ld:AirQualityObserved:barcelona.cat:barcelona:xvpca-"
# The run's clock for the recording: 57 minutes after the newest hour it holds.
AS_OF = {"bcn_now": "2026-10-22T19:57:00Z"}
BBOX = yaml.safe_load((CITY / "barcelona-space.yaml").read_text())["spec"]["quality"][0]["bbox"]


def run(document: str, now: dict = AS_OF) -> list[dict]:
    return open_data.run_all(MAPPING, document.encode(), "barcelona", "barcelona.cat", now)


def first_step(document: str, now: dict = AS_OF) -> dict:
    """What the first step answers, read before the last step keeps only the entities: its
    `dropped` counts, or the error it raised."""
    handle, name = tempfile.mkstemp(suffix=".yaml")
    os.close(handle)
    trimmed = Path(name)
    pipeline = yaml.safe_load(MAPPING.read_text())
    pipeline["pipeline"]["processors"] = pipeline["pipeline"]["processors"][:1] + [
        {"mapping": 'root = if errored() { { "error": error() } } else { this }'}]
    trimmed.write_text(yaml.safe_dump(pipeline))
    try:
        return open_data.run_all(trimmed, document.encode(), "barcelona", "barcelona.cat", now)[0]
    finally:
        trimmed.unlink()


def dropped(document: str) -> dict:
    return first_step(document)["dropped"]


def edited(edit) -> str:
    rows = list(csv.reader(io.StringIO(RECORDED)))
    edit(rows)
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def row(rows, station: str, code: str, day: str) -> list[str]:
    return next(r for r in rows if r[4] == station and r[5] == code and r[8] == day)


@pytest.fixture(scope="module")
def written():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {e["id"]: e for e in run(RECORDED)}


@requires_docker
def test_every_station_of_the_file_is_one_entity_with_its_newest_valid_hour(written):
    assert len(written) == 9
    eixample = written[PREFIX + "8019043"]
    # Station 43, NO2 (code 8), 2026-10-22: H21 is the newest "V" hour, 21:00 CEST = 19:00Z.
    no2 = row(list(csv.reader(io.StringIO(RECORDED))), "043", "8", "22")
    assert eixample["no2"] == {"type": "Property", "value": float(no2[9 + 2 * 20]), "unitCode": "GQ",
                               "observedAt": "2026-10-22T19:00:00Z"}
    assert eixample["co"]["unitCode"] == "GP"
    assert eixample["dateObserved"] == {"type": "Property", "value": "2026-10-22T19:00:00Z"}
    assert eixample["name"] == {"type": "LanguageProperty", "languageMap": {"ca": "Barcelona - Eixample"}}
    assert eixample["address"]["value"] == {"streetAddress": "Av. Roma - c/ Comte Urgell", "addressLocality": "Barcelona",
                                            "district": "Eixample", "addressCountry": "ES"}
    assert eixample["stationCode"]["value"] == "8019043"
    # Black carbon arrives in ng/m³ (827 at 10:00 CEST beside PM2.5 6 µg/m³) and is written in µg/m³.
    bc = row(list(csv.reader(io.StringIO(RECORDED))), "043", "22", "22")
    newest = max(h for h in range(1, 25) if bc[8 + 2 * h] == "V")
    assert eixample["blackCarbon"]["value"] == pytest.approx(float(bc[7 + 2 * newest]) / 1000)
    assert eixample["blackCarbon"]["value"] < eixample["pm25"]["value"]


@requires_docker
def test_every_entity_is_one_the_gateway_accepts_and_valid_in_its_smart_data_model(written):
    for entity in written.values():
        assert open_data.schema_errors(CITY / "barcelona.v1.schema.json", entity) == [], entity["id"]
        assert open_data.sdm_errors("dataModel.Environment/AirQualityObserved", entity) == [], entity["id"]


@requires_docker
def test_every_station_stands_inside_the_city_and_each_reading_in_its_physical_range(written):
    for entity in written.values():
        lon, lat = entity["location"]["value"]["coordinates"]
        assert BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3], entity["id"]
        for name in ("so2", "co", "no", "no2", "nox", "o3", "pm10", "pm25", "blackCarbon"):
            if name in entity:
                assert 0 <= entity[name]["value"] <= 3000, (entity["id"], name)
                assert entity[name]["observedAt"] <= "2026-10-22T19:57:00Z"


@requires_docker
def test_the_recording_drops_only_the_hours_the_city_marks_not_valid():
    counts = dropped(RECORDED)
    # 316 rows; the internal flows, the biomass share and the codes 1xx, 11, 901 are no reading.
    assert counts["duplicateRow"] == 0 and counts["outOfRange"] == 0 and counts["inTheFuture"] == 0
    assert counts["unknownStationOrPollutant"] > 0 and counts["notValid"] > 0


@requires_docker
def test_an_unknown_station_an_out_of_range_value_and_a_duplicate_are_dropped_and_counted():
    def edit(rows):
        # A station the network list does not name, with a place nobody can check.
        rows.append(["08", "Barcelona", "019", "Barcelona", "099", "8"] + row(rows, "043", "8", "22")[6:])
        # NO2 at Eixample reads 99999 µg/m³ at 21:00: the 20:00 hour before it stands.
        row(rows, "043", "8", "22")[9 + 2 * 20] = "99999"
        # Sants' NO2 of the day twice, the second copy with another value: the first stands.
        copy = list(row(rows, "042", "8", "22"))
        copy[9 + 2 * 20] = "1"
        rows.append(copy)
    document = edited(edit)
    counts = dropped(document)
    assert counts["unknownStationOrPollutant"] == dropped(RECORDED)["unknownStationOrPollutant"] + 1
    assert counts["outOfRange"] == 1
    assert counts["duplicateRow"] == 1
    entities = {e["id"]: e for e in run(document)}
    assert len(entities) == 9
    assert entities[PREFIX + "8019043"]["no2"]["observedAt"] == "2026-10-22T18:00:00Z"
    original = row(list(csv.reader(io.StringIO(RECORDED))), "042", "8", "22")
    assert entities[PREFIX + "8019042"]["no2"]["value"] == float(original[9 + 2 * 20])


@requires_docker
def test_a_file_without_a_valid_reading_or_a_stale_one_fails_the_run_and_writes_nothing():
    header = RECORDED.splitlines()[0] + "\n"
    assert "no valid reading" in first_step(header)["error"]
    assert "more than three hours old" in first_step(RECORDED, {"bcn_now": "2026-10-22T22:30:00Z"})["error"]


@requires_docker
def test_local_hours_become_utc_across_the_change_to_winter_time():
    def edit(rows):
        r = row(rows, "043", "8", "22")
        r[6:9] = ["2026", "10", "25"]
        # H01..H24 all valid: H24 ends at midnight CET, 23:00Z.
        for h in (22, 23, 24):
            r[7 + 2 * h], r[8 + 2 * h] = "20", "V"
        rows[:] = [rows[0], r]
    entity = run(edited(edit), {"bcn_now": "2026-10-25T23:30:00Z"})[0]
    assert entity["no2"]["observedAt"] == "2026-10-25T23:00:00Z"


def test_the_pipeline_upserts_from_the_one_datasource_through_the_spaces_door():
    pipeline = yaml.safe_load((CITY / "barcelona-pipeline-air-quality.yaml").read_text())["spec"]
    source = yaml.safe_load((CITY / "barcelona-datasource-air-quality.yaml").read_text())["spec"]["http"]
    assert source["url"].startswith("https://opendata-ajuntament.barcelona.cat/")
    assert pipeline["output"] == {"type": "AirQualityObserved", "mode": "upsert"}
    assert pipeline["targetEndpoint"] == "urn:ngsi-ld:Endpoint:barcelona.cat:barcelona:barcelona"


def test_the_dataset_endpoint_publishes_to_ckan_through_its_read_only_policy():
    endpoint = yaml.safe_load((CITY / "barcelona-endpoint-air-quality.yaml").read_text())["spec"]
    policy = yaml.safe_load((CITY / "barcelona-policy-public-air-quality.yaml").read_text())["spec"]
    assert endpoint["policyRef"].endswith(":public-air-quality")
    assert endpoint["publish"]["ckan"]["instanceRef"]["name"] == "barcelona"
    assert {"ngsi-ld", "csv", "ogc-features", "odata"} <= set(endpoint["enabledRepresentations"])
    assert policy["information"] == [{"entities": [{"type": "AirQualityObserved"}]}]
    assert not {"upsertBatch", "createBatch", "deleteBatch", "createEntity", "deleteEntity"} & set(policy["operations"])
    assert json.dumps(policy["assignee"]) == json.dumps({"kind": "role", "id": "public"})
