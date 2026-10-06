"""Every Žilina mapping over a recorded answer of the real feed (T-3138, PL-03, PL-64).

The committed Bloblang runs in the pinned Bento over documents recorded on 2026-10-06 from the
URL each `DataSource` declares (fixtures/zilina), so a mapping checked here is a mapping that ran.
The empty-read guard every stream starts with is checked the same way: an answer with nothing in
it fails the run instead of writing nothing as if the city had emptied.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import open_data
from open_data import BENTO, requires_docker

pytestmark = pytest.mark.xdist_group("docker-zilina-pipelines")

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "components/context-gateway/seed/zilina"
FIXTURES = Path(__file__).resolve().parent / "fixtures/zilina"
DOMAIN = "zilina.sk"
CITY = "SK031B517402"


def pipelines(prefix: str) -> dict[str, dict]:
    """Every pipeline manifest of the seed whose DataSource name starts with `prefix`."""
    found = {}
    for path in sorted(SEED.glob("zilina-pipeline-*.yaml")):
        if path.name.endswith("-bento.yaml"):
            continue
        manifest = yaml.safe_load(path.read_text())
        source = manifest["spec"]["source"]["dataSourceRef"]["name"]
        if source.startswith(prefix):
            found[manifest["metadata"]["name"]] = {"source": source, "manifest": manifest,
                                                   "bento": path.with_name(path.stem + "-bento.yaml")}
    return found


CUBES = pipelines("susr-")
STATIONS = pipelines("eea-")


def run(pipeline: dict, space: str) -> list[dict]:
    suffix = ".parquet" if pipeline["source"].startswith("eea-") else ".json"
    document = (FIXTURES / (pipeline["source"] + suffix)).read_bytes()
    return open_data.run(pipeline["bento"], document, space, DOMAIN)


@pytest.fixture(scope="module")
def cubes():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(p, "zilina-mesto") for name, p in CUBES.items()}


@pytest.fixture(scope="module")
def stations():
    if shutil.which("docker") is None:
        pytest.skip("no container runtime")
    return {name: run(p, "zilina-verejne") for name, p in STATIONS.items()}


def test_every_inventoried_source_has_its_pipeline():
    assert len(CUBES) == 16 and len(STATIONS) == 5
    for p in [*CUBES.values(), *STATIONS.values()]:
        spec = p["manifest"]["spec"]
        assert spec["targetEndpoint"].startswith("urn:ngsi-ld:Endpoint:zilina.sk:")
        assert spec["schedule"], "every stream runs on a schedule"
        assert (SEED / f"zilina-datasource-{p['manifest']['metadata']['name']}.yaml").is_file()


def test_every_stream_starts_with_the_empty_read_guard():
    for p in [*CUBES.values(), *STATIONS.values()]:
        assert "throw(" in p["bento"].read_text(), p["bento"].name


@requires_docker
def test_every_cube_cell_becomes_one_observation_of_the_city(cubes):
    schema = SEED / "statistical-observation.v1.schema.json"
    for name, entities in cubes.items():
        source = json.loads((FIXTURES / (CUBES[name]["source"] + ".json")).read_text())
        cells = [v for v in (source["value"] if isinstance(source["value"], list) else source["value"].values()) if v is not None]
        assert len(entities) == len(cells), name
        ids = [e["id"] for e in entities]
        assert len(set(ids)) == len(ids), f"{name}: two cells share an id"
        for entity in entities[:50]:
            assert entity["type"] == "StatisticalObservation"
            assert entity["id"].split(":")[3:5] == [DOMAIN, "zilina-mesto"]
            assert entity["refArea"]["value"] == CITY, name
            assert not open_data.schema_errors(schema, entity), (name, open_data.schema_errors(schema, entity))


@requires_docker
def test_the_population_of_the_city_is_the_one_ŠÚ_SR_publishes(cubes):
    end_of_quarter = {e["id"]: e for e in cubes["obyvatelstvo"]}[
        f"urn:ngsi-ld:StatisticalObservation:{DOMAIN}:zilina-mesto:om7101qr-{CITY}-2026Q2-IN010115-SPOLU"]
    assert end_of_quarter["value"]["value"] == 79617


@requires_docker
def test_the_station_is_one_entity_and_each_pollutant_its_own_reading(stations):
    expected = {
        "ovzdusie-pm10": ("pm10", 32.341, "GQ", "2026-10-06T18:00:00Z"),
        "ovzdusie-pm25": ("pm25", 15.417, "GQ", "2026-10-06T18:00:00Z"),
        "ovzdusie-no2": ("no2", 28.1313, "GQ", "2026-10-06T18:00:00Z"),
        # Every ozone hour of the recording carries validity 4, EEA's valid ozone reading.
        "ovzdusie-o3": ("o3", 11.8076, "GQ", "2026-10-05T17:00:00Z"),
        # The file's Unit column says mg.m-3: UN/CEFACT GP, never µg/m³.
        "ovzdusie-co": ("co", 0.63452, "GP", "2026-10-06T18:00:00Z"),
    }
    schema = SEED / "zilina-verejne.v1.schema.json"
    for name, (attribute, value, unit, at) in expected.items():
        [station] = stations[name]
        assert station["id"] == f"urn:ngsi-ld:AirQualityObserved:{DOMAIN}:zilina-verejne:eea-SK0020A"
        reading = station[attribute]
        assert (reading["value"], reading["unitCode"], reading["observedAt"]) == (value, unit, at), name
        assert station["location"]["value"] == {"type": "Point", "coordinates": [18.771215, 49.211447]}
        others = {"pm10", "pm25", "no2", "o3", "co"} - {attribute}
        assert not others & set(station), f"{name} writes only its own pollutant"
        assert not open_data.schema_errors(schema, station), open_data.schema_errors(schema, station)


def guard(path: Path) -> str:
    return next(step["mapping"] for step in yaml.safe_load(path.read_text())["pipeline"]["processors"]
                if "mapping" in step and "throw(" in step["mapping"])


def blobl(mapping: str, document: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "run", "--rm", "-i", BENTO, "blobl", mapping],
                          input=document, capture_output=True, text=True, timeout=120)


@requires_docker
def test_an_empty_cube_answer_fails_the_run_and_a_full_one_passes():
    mapping = guard(CUBES["obyvatelstvo"]["bento"])
    empty = blobl(mapping, json.dumps({"value": [], "id": [], "size": []}) + "\n")
    assert "the cube answered no cell" in empty.stdout + empty.stderr
    refused = blobl(mapping, json.dumps({"status": 400, "status_message": "Bad number of dimension cubes"}) + "\n")
    assert "Bad number of dimension cubes" in refused.stdout + refused.stderr
    full = blobl(mapping, json.dumps({"value": [1]}) + "\n")
    assert '"value":[1]' in full.stdout.replace(" ", ""), full.stdout + full.stderr


@requires_docker
def test_an_empty_station_file_fails_the_run():
    mapping = guard(STATIONS["ovzdusie-pm10"]["bento"])
    empty = blobl(mapping, "[]\n")
    assert "the station file holds no record" in empty.stdout + empty.stderr
